"""Gap #6 — Unicode-aware alias normalization (NFKC + casefold + collapse).

``normalize_alias`` is the single source for alias norms (customer matching,
intelligence import ``_norm``, the alias write rules). These pins prove the
Unicode classes now fold correctly and the ASCII behavior is byte-identical
to the legacy lower+collapse form.
"""
from backend.models.customer_alias import CustomerAlias
from backend.models.use_case import Customer
from backend.services import customer_alias_service
from backend.services.customer_alias_service import normalize_alias
from backend.services.customer_match import CustomerMatcher
from backend.services.intelligence_import_service import _norm

FULLWIDTH = "ＮｏｒｔｈｗｉｎｄＦ Ｇｒｏｕｐ"
LIGATURE = "ﬁle Co"
SHARP_S = "Straße AG"
ACCENTED = "ÉLEKTRONIK GmbH"


def test_full_width_folds_to_ascii():
    assert normalize_alias(FULLWIDTH) == "northwindf group"
    assert normalize_alias("ＮｏｒｔｈｗｉｎｄＦ  Ｇｒｏｕｐ ") == "northwindf group"


def test_ligature_folds():
    assert normalize_alias(LIGATURE) == "file co"


def test_sharp_s_casefolds_to_ss():
    assert normalize_alias(SHARP_S) == "strasse ag"
    assert normalize_alias("Strasse AG") == normalize_alias(SHARP_S)


def test_accented_is_case_insensitive():
    assert normalize_alias(ACCENTED) == "élektronik gmbh"
    assert normalize_alias("élektronik gmbh") == normalize_alias(ACCENTED)


def test_ascii_corpus_is_byte_identical_to_the_legacy_norm():
    legacy = lambda v: " ".join((v or "").lower().split())
    corpus = [
        "Acme Manufacturing", "  A C M E   MFG ", "w.R. Berkley", "Zeta Co",
        "Synthetic Alpha & Beta LLC", "123 Main St", "a-b_c.d e", "",
        "MIXEDCase Names 123",
    ]
    for value in corpus:
        assert normalize_alias(value) == legacy(value)
    assert normalize_alias(None) == ""


def test_import_norm_is_the_alias_norm():
    corpus = ["Acme", FULLWIDTH, LIGATURE, SHARP_S, ACCENTED, "  spaced  out ", ""]
    for value in corpus:
        assert _norm(value) == normalize_alias(value)


def test_matcher_resolves_a_full_width_alias(db_session):
    customer = Customer(name="W.R. Berkley")
    db_session.add(customer)
    db_session.flush()
    alias_text = "Ｂｅｒｋｌｅｙ Ｗｉｒｅｌｅｓｓ"
    db_session.add(CustomerAlias(customer_id=customer.id, alias=alias_text,
                                 alias_norm=normalize_alias(alias_text)))
    db_session.flush()
    matcher = CustomerMatcher(db_session)
    assert matcher.resolve("w.r. berkley") == (customer, "name")
    assert matcher.resolve("berkley  wireless") == (customer, "alias")
    assert matcher.resolve(alias_text) == (customer, "alias")


def test_add_alias_rejects_a_unicode_collision_with_a_customer_name(db_session):
    # Customer A's name is "Strasse" (norm "strasse"); an alias on customer B
    # whose NEW norm is "strasse" ("Straße" — legacy norm "straße") must be
    # rejected, although the legacy normalization would have accepted it.
    first = Customer(name="Strasse")
    second = Customer(name="Zeta Co")
    db_session.add_all([first, second])
    db_session.flush()
    import pytest
    with pytest.raises(ValueError, match=customer_alias_service.OTHER_NAME):
        customer_alias_service.add_alias(db_session, second, "Straße", "admin")


def test_add_alias_accepts_a_full_width_alias(db_session):
    customer = Customer(name="Acme Manufacturing")
    db_session.add(customer)
    db_session.flush()
    row = customer_alias_service.add_alias(db_session, customer, FULLWIDTH, "admin")
    assert row.alias_norm == "northwindf group"
