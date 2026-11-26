"""Matching and suggestions never resolve ambiguity by filtering customer scope."""

from backend.models.customer_alias import CustomerAlias
from backend.models.use_case import Customer
from backend.services.customer_match import CustomerMatcher


def test_names_aliases_and_suggestions(db_session):
    first = Customer(name="Synthetic Alpha & Beta LLC")
    second = Customer(name="Synthetic Other")
    db_session.add_all([first, second])
    db_session.flush()
    db_session.add(CustomerAlias(customer_id=first.id, alias="Synthetic Legacy Inc",
                                 alias_norm="synthetic legacy inc"))
    db_session.flush()
    matcher = CustomerMatcher(db_session)
    assert matcher.resolve(" SYNTHETIC Alpha & Beta LLC ") == (first, "name")
    assert matcher.resolve("synthetic   legacy inc") == (first, "alias")
    assert matcher.resolve("Synthetic Alpha and Beta")[0] is None
    expected = {"customer_id": first.id, "customer_name": first.name}
    assert matcher.suggest("Synthetic Alpha and Beta", None) == expected
    assert matcher.suggest("Synthetic Legacy", {first.id}) == expected
    assert matcher.suggest("Synthetic Legacy", {second.id}) is None
    assert matcher.suggest("Missing", None) is None
    assert matcher.suggest("", None) is None


def test_ambiguity_is_global(db_session):
    first = Customer(name="Synthetic Collision LLC")
    second = Customer(name="Synthetic Collision Inc")
    db_session.add_all([first, second])
    db_session.flush()
    db_session.add(CustomerAlias(customer_id=second.id, alias=first.name,
                                 alias_norm=first.name.lower()))
    db_session.flush()
    matcher = CustomerMatcher(db_session)
    assert matcher.resolve(first.name) == (None, "ambiguous")
    assert matcher.suggest("Synthetic Collision", {first.id}) is None
    assert matcher.suggest("Synthetic Collision", None) is None


def test_duplicate_normalized_names_are_ambiguous(db_session):
    db_session.add_all([Customer(name="Synthetic Spacing"), Customer(name="SYNTHETIC  SPACING")])
    db_session.flush()
    matcher = CustomerMatcher(db_session)
    assert matcher.resolve("synthetic spacing") == (None, "ambiguous")
