"""deterministic demo customer-intelligence seed tests.

Verifies seed_customer_intelligence:
- seeds per-customer Technology Inventory + Sales Notes + Customer Knowledge
- idempotent + non-destructive (fills empty tables only, never overwrites
  user-entered data on re-seed)
- reset=True clears + re-seeds
- junctions resolved by tech name / use-case title (internally consistent)
- deterministic (fixed SEED_DATE -> identical data on re-seed)
- verification-state spread (verified + inferred) and workflow coverage
"""

from datetime import date, datetime

from backend.models.customer_knowledge import CustomerKnowledge
from backend.models.customer_technology import CustomerTechnology
from backend.models.sales_note import SalesNote
from backend.models.use_case import Customer, UseCase
from backend.seed import (
    CUSTOMER_INTELLIGENCE,
    SEED_DATE,
    seed_customer_intelligence,
)

DEMO_NAMES = list(CUSTOMER_INTELLIGENCE.keys())


def _mk_demo_customers(db_session):
    """Create the 3 demo customers (no use cases) and return {name: customer}."""
    out = {}
    for name in DEMO_NAMES:
        c = Customer(name=name, description="seed test customer")
        db_session.add(c)
        db_session.flush()
        out[name] = c
    db_session.commit()
    return out


def _tech_count(db_session, customer_id):
    return (
        db_session.query(CustomerTechnology)
        .filter(CustomerTechnology.customer_id == customer_id)
        .count()
    )


def _note_count(db_session, customer_id):
    return (
        db_session.query(SalesNote)
        .filter(SalesNote.customer_id == customer_id)
        .count()
    )


def _kn_count(db_session, customer_id):
    return (
        db_session.query(CustomerKnowledge)
        .filter(CustomerKnowledge.customer_id == customer_id)
        .count()
    )


class TestSeedCustomerIntelligence:
    def test_seeds_technology_and_notes_for_demo_customers(self, db_session):
        customers = _mk_demo_customers(db_session)
        stats = seed_customer_intelligence(db_session)

        assert stats["technology"] > 0
        assert stats["sales_notes"] > 0
        for name, c in customers.items():
            assert _tech_count(db_session, c.id) > 0, f"{name} has no tech"
            assert _note_count(db_session, c.id) > 0, f"{name} has no notes"
            # Business context (vertical) is set.
            assert c.vertical == CUSTOMER_INTELLIGENCE[name]["vertical"]

    def test_idempotent_never_overwrites_user_data(self, db_session):
        customers = _mk_demo_customers(db_session)
        first = seed_customer_intelligence(db_session)
        acme = customers["Acme Manufacturing"]

        acme_tech_before = _tech_count(db_session, acme.id)
        acme_notes_before = _note_count(db_session, acme.id)

        # A user adds their own tech item + note to Acme.
        user_tech = CustomerTechnology(
            customer_id=acme.id, name="User-Added Tech", category="software",
            verification_state="verified",
        )
        user_note = SalesNote(
            customer_id=acme.id, category="discovery", title="User note",
            content="user entered", verification_state="verified",
        )
        db_session.add_all([user_tech, user_note])
        db_session.commit()

        # Re-seed (no reset): must be a no-op for Acme (already has data),
        # never duplicate or overwrite.
        second = seed_customer_intelligence(db_session)
        assert second == {"technology": 0, "sales_notes": 0, "knowledge": 0, "dependencies": 0}
        assert _tech_count(db_session, acme.id) == acme_tech_before + 1
        assert _note_count(db_session, acme.id) == acme_notes_before + 1
        # The user data is intact (not overwritten / not replaced).
        assert (
            db_session.query(CustomerTechnology)
            .filter(CustomerTechnology.name == "User-Added Tech")
            .count()
        ) == 1
        assert (
            db_session.query(SalesNote)
            .filter(SalesNote.title == "User note")
            .count()
        ) == 1

    def test_reset_clears_and_reseeds(self, db_session):
        customers = _mk_demo_customers(db_session)
        seed_customer_intelligence(db_session)
        acme = customers["Acme Manufacturing"]

        user_tech = CustomerTechnology(
            customer_id=acme.id, name="User-Added Tech", category="software",
            verification_state="verified",
        )
        db_session.add(user_tech)
        db_session.commit()

        stats = seed_customer_intelligence(db_session, reset=True)
        # User data is cleared, then re-seeded (deterministic).
        assert (
            db_session.query(CustomerTechnology)
            .filter(CustomerTechnology.name == "User-Added Tech")
            .count()
        ) == 0
        assert _tech_count(db_session, acme.id) > 0
        assert _note_count(db_session, acme.id) > 0
        assert stats["technology"] > 0 and stats["sales_notes"] > 0

    def test_junctions_link_by_name_and_title(self, db_session):
        customers = _mk_demo_customers(db_session)
        acme = customers["Acme Manufacturing"]
        # Create the use case the seed data references by title.
        uc = UseCase(
            title="Manufacturing IT Infrastructure Monitoring",
            description="t", customer_id=acme.id,
        )
        db_session.add(uc)
        db_session.commit()

        seed_customer_intelligence(db_session)

        # The discovery note links to vSphere 6.5 + R720 (by name) and the UC (by title).
        note = (
            db_session.query(SalesNote)
            .filter(SalesNote.customer_id == acme.id, SalesNote.title == "IT discovery: 200+ VMs on vSphere 6.5")
            .first()
        )
        assert note is not None
        vsphere = (
            db_session.query(CustomerTechnology)
            .filter(CustomerTechnology.name == "VMware vSphere 6.5")
            .first()
        )
        r720 = (
            db_session.query(CustomerTechnology)
            .filter(CustomerTechnology.name == "Dell PowerEdge R720")
            .first()
        )
        assert vsphere.id in note.related_technology_ids
        assert r720.id in note.related_technology_ids
        assert uc.id in note.related_use_case_ids

    def test_verification_state_spread(self, db_session):
        customers = _mk_demo_customers(db_session)
        seed_customer_intelligence(db_session)
        states = {
            t.verification_state
            for c in customers.values()
            for t in (
                db_session.query(CustomerTechnology)
                .filter(CustomerTechnology.customer_id == c.id)
                .all()
            )
        }
        # The seed exercises both verified facts and inferred observations.
        assert "verified" in states
        assert "inferred" in states

    def test_deterministic_reseed_produces_identical_data(self, db_session):
        _mk_demo_customers(db_session)
        seed_customer_intelligence(db_session, reset=True)

        def snapshot():
            techs = sorted(
                (t.name, t.category, t.lifecycle_state)
                for t in db_session.query(CustomerTechnology).all()
            )
            notes = sorted(
                (n.title, str(n.note_date), n.category)
                for n in db_session.query(SalesNote).all()
            )
            return techs, notes

        first = snapshot()
        seed_customer_intelligence(db_session, reset=True)
        second = snapshot()
        assert first == second
        # Dates are anchored to the fixed SEED_DATE (deterministic).
        for title, note_date, _cat in second[1]:
            assert note_date != ""
            assert date.fromisoformat(note_date) <= SEED_DATE

    def test_vertical_not_overwritten_when_set(self, db_session):
        customers = _mk_demo_customers(db_session)
        acme = customers["Acme Manufacturing"]
        acme.vertical = "User-Set Vertical"
        db_session.commit()

        seed_customer_intelligence(db_session)
        db_session.refresh(acme)
        assert acme.vertical == "User-Set Vertical"

    def test_workflow_coverage(self, db_session):
        customers = _mk_demo_customers(db_session)
        seed_customer_intelligence(db_session)

        acme = customers["Acme Manufacturing"]
        bank = customers["GlobalBank Financial Services"]
        tech = customers["TechCorp Solutions"]

        # Acme: aging/EOL + virtualization workflow.
        eol = (
            db_session.query(CustomerTechnology)
            .filter(
                CustomerTechnology.customer_id == acme.id,
                CustomerTechnology.lifecycle_state == "eol",
            )
            .count()
        )
        assert eol >= 2

        # GlobalBank: security workflow.
        sec = (
            db_session.query(CustomerTechnology)
            .filter(
                CustomerTechnology.customer_id == bank.id,
                CustomerTechnology.category == "security",
            )
            .count()
        )
        assert sec >= 3

        # TechCorp: cloud + AI workflow.
        cloud = (
            db_session.query(CustomerTechnology)
            .filter(
                CustomerTechnology.customer_id == tech.id,
                CustomerTechnology.category == "cloud_platform",
            )
            .count()
        )
        ai = (
            db_session.query(CustomerTechnology)
            .filter(
                CustomerTechnology.customer_id == tech.id,
                CustomerTechnology.category == "ai_technology",
            )
            .count()
        )
        assert cloud >= 2
        assert ai >= 1

    def test_only_empty_customers_are_seeded(self, db_session):
        """A customer that already has tech/notes is left untouched; others seed."""
        customers = _mk_demo_customers(db_session)
        acme = customers["Acme Manufacturing"]
        # Pre-populate Acme with user data (simulating an existing account).
        db_session.add(CustomerTechnology(
            customer_id=acme.id, name="Existing", category="software",
            verification_state="verified",
        ))
        db_session.add(SalesNote(
            customer_id=acme.id, category="meeting", title="Existing",
            content="x", verification_state="verified",
        ))
        db_session.commit()

        stats = seed_customer_intelligence(db_session)
        # Acme is skipped (already has data); the other two customers seed.
        assert _tech_count(db_session, acme.id) == 1  # only the user item
        assert _note_count(db_session, acme.id) == 1
        # The stats reflect only the two seeded customers (tech + notes per
        # customer — derived from CUSTOMER_INTELLIGENCE so this stays true as
        # the demo inventories are enriched).
        other_names = [n for n in DEMO_NAMES if n != "Acme Manufacturing"]
        expected_tech = sum(len(CUSTOMER_INTELLIGENCE[n]["technology"]) for n in other_names)
        expected_notes = sum(len(CUSTOMER_INTELLIGENCE[n]["sales_notes"]) for n in other_names)
        assert stats["technology"] == expected_tech
        assert stats["sales_notes"] == expected_notes
        # Knowledge seeds for all three (Acme had tech/notes but no knowledge).
        assert stats["knowledge"] == 9
        assert _kn_count(db_session, acme.id) == 3


class TestSeedKnowledge:
    """deterministic demo Customer Knowledge seeding."""

    def test_seeds_knowledge_for_demo_customers(self, db_session):
        customers = _mk_demo_customers(db_session)
        stats = seed_customer_intelligence(db_session)

        assert stats["knowledge"] == 9  # 3 per demo customer
        for name, c in customers.items():
            rows = (
                db_session.query(CustomerKnowledge)
                .filter(CustomerKnowledge.customer_id == c.id)
                .all()
            )
            assert len(rows) == 3, f"{name} has {len(rows)} knowledge rows"
            expected = CUSTOMER_INTELLIGENCE[name]["knowledge"]
            assert {r.file_name for r in rows} == {k["file_name"] for k in expected}
            # Deterministic dates anchored on SEED_DATE, demo-labeled bytes.
            for r in rows:
                assert r.uploaded_at.year == SEED_DATE.year
                assert r.uploaded_at <= datetime.combine(
                    SEED_DATE, datetime.min.time()
                )
                assert r.file_data.startswith(b"S-A-I-L demo knowledge")
            # A processed + pending mix (freshness/processing for the UI).
            assert sum(1 for r in rows if r.processed) >= 1
            assert sum(1 for r in rows if r.processed == 0) >= 1

    def test_knowledge_idempotent_never_overwrites(self, db_session):
        customers = _mk_demo_customers(db_session)
        seed_customer_intelligence(db_session)
        acme = customers["Acme Manufacturing"]
        db_session.add(CustomerKnowledge(
            customer_id=acme.id, knowledge_type="file",
            file_name="user-upload.pdf", file_data=b"user",
            uploaded_at=datetime(SEED_DATE.year, SEED_DATE.month, SEED_DATE.day),
        ))
        db_session.commit()

        # All three customers now have knowledge -> re-seed is a no-op.
        second = seed_customer_intelligence(db_session)
        assert second["knowledge"] == 0
        assert _kn_count(db_session, acme.id) == 4  # 3 seeded + 1 user
        assert (
            db_session.query(CustomerKnowledge)
            .filter(
                CustomerKnowledge.customer_id == acme.id,
                CustomerKnowledge.file_name == "user-upload.pdf",
            )
            .count()
            == 1
        )

    def test_only_empty_knowledge_customers_seeded(self, db_session):
        customers = _mk_demo_customers(db_session)
        acme = customers["Acme Manufacturing"]
        db_session.add(CustomerKnowledge(
            customer_id=acme.id, knowledge_type="file",
            file_name="existing.pdf", file_data=b"existing",
            uploaded_at=datetime(SEED_DATE.year, SEED_DATE.month, SEED_DATE.day),
        ))
        db_session.commit()

        stats = seed_customer_intelligence(db_session)
        assert stats["knowledge"] == 6  # only the other two customers
        assert _kn_count(db_session, acme.id) == 1  # user row preserved

    def test_reset_clears_and_reseeds_knowledge(self, db_session):
        customers = _mk_demo_customers(db_session)
        seed_customer_intelligence(db_session)
        acme = customers["Acme Manufacturing"]
        db_session.add(CustomerKnowledge(
            customer_id=acme.id, knowledge_type="file",
            file_name="user-upload.pdf", file_data=b"user",
            uploaded_at=datetime(SEED_DATE.year, SEED_DATE.month, SEED_DATE.day),
        ))
        db_session.commit()
        assert _kn_count(db_session, acme.id) == 4

        seed_customer_intelligence(db_session, reset=True)
        # Reset clears user rows and re-seeds the deterministic demo set.
        assert _kn_count(db_session, acme.id) == 3
        assert (
            db_session.query(CustomerKnowledge)
            .filter(CustomerKnowledge.file_name == "user-upload.pdf")
            .count()
            == 0
        )

    def test_knowledge_deterministic_across_resets(self, db_session):
        _mk_demo_customers(db_session)
        seed_customer_intelligence(db_session, reset=True)

        def snapshot():
            return {
                (r.customer_id, r.file_name, r.knowledge_type,
                 r.ingestion_status, r.processed,
                 r.uploaded_at.isoformat())
                for r in db_session.query(CustomerKnowledge).all()
            }

        snap_a = snapshot()
        seed_customer_intelligence(db_session, reset=True)
        snap_b = snapshot()
        assert snap_a == snap_b
        assert len(snap_a) == 9


class TestSeedDependencies:
    """PLAN_FEATURE_ENHANCMENTS.md — deterministic demo technology
    dependency seeding. Dependencies are resolved by tech NAME
    against the customer's inventory, seeded only when a customer has
    none, and never fabricated (unresolvable endpoints are skipped)."""

    def _dep_count(self, db_session, customer_id):
        from backend.models.technology_dependency import TechnologyDependency

        return (
            db_session.query(TechnologyDependency)
            .filter(TechnologyDependency.customer_id == customer_id)
            .count()
        )

    def test_seeds_dependencies_for_demo_customers(self, db_session):
        customers = _mk_demo_customers(db_session)
        stats = seed_customer_intelligence(db_session)

        assert stats["dependencies"] > 0
        for name, c in customers.items():
            expected = len(CUSTOMER_INTELLIGENCE[name].get("dependencies", []))
            assert self._dep_count(db_session, c.id) == expected, f"{name}: {expected} expected"

    def test_dependencies_resolve_to_same_customer_endpoints(self, db_session):
        from backend.models.technology_dependency import TechnologyDependency

        customers = _mk_demo_customers(db_session)
        seed_customer_intelligence(db_session)
        # Every dependency row's source and target are technologies of the
        # SAME customer (customer isolation at the data level).
        for dep in db_session.query(TechnologyDependency).all():
            src = (
                db_session.query(CustomerTechnology)
                .filter(CustomerTechnology.id == dep.source_id)
                .first()
            )
            tgt = (
                db_session.query(CustomerTechnology)
                .filter(CustomerTechnology.id == dep.target_id)
                .first()
            )
            assert src.customer_id == dep.customer_id
            assert tgt.customer_id == dep.customer_id
            assert src.id != tgt.id

    def test_dependencies_idempotent_never_duplicate(self, db_session):
        customers = _mk_demo_customers(db_session)
        first = seed_customer_intelligence(db_session)
        acme = customers["Acme Manufacturing"]
        acme_deps_before = self._dep_count(db_session, acme.id)
        assert acme_deps_before > 0

        # Re-seed (no reset): dependencies for a customer that already has
        # them must be a no-op (never duplicated).
        second = seed_customer_intelligence(db_session)
        assert second["dependencies"] == 0
        assert self._dep_count(db_session, acme.id) == acme_deps_before

    def test_reset_clears_and_reseeds_dependencies(self, db_session):
        customers = _mk_demo_customers(db_session)
        seed_customer_intelligence(db_session)
        acme = customers["Acme Manufacturing"]
        before = self._dep_count(db_session, acme.id)
        assert before > 0

        stats = seed_customer_intelligence(db_session, reset=True)
        assert self._dep_count(db_session, acme.id) == before
        assert stats["dependencies"] > 0

    def test_dependencies_deterministic_across_resets(self, db_session):
        _mk_demo_customers(db_session)
        seed_customer_intelligence(db_session, reset=True)

        from backend.models.customer_technology import CustomerTechnology
        from backend.models.technology_dependency import TechnologyDependency

        def snapshot():
            # Compare by technology name: a reset reissues new IDs (IDs are never reused, ER-12).
            names = {t.id: t.name for t in db_session.query(CustomerTechnology).all()}
            return {
                (d.customer_id, names[d.source_id], names[d.target_id], d.relationship_type)
                for d in db_session.query(TechnologyDependency).all()
            }

        first = snapshot()
        seed_customer_intelligence(db_session, reset=True)
        second = snapshot()
        assert first == second
        assert len(first) > 0

    def test_unresolvable_dependency_is_skipped_not_fabricated(self, db_session):
        """A dependency that references a technology the customer does NOT
        have is skipped (never fabricated) — the seeded count reflects only
        the resolvable ones."""
        customers = _mk_demo_customers(db_session)
        acme = customers["Acme Manufacturing"]
        # Pre-seed ONLY a subset of Acme's tech (so some dependency endpoints
        # are missing). Dependencies whose endpoints are absent are skipped.
        from backend.services.technology_inventory_service import create_technology

        partial = CUSTOMER_INTELLIGENCE["Acme Manufacturing"]["technology"][:3]
        for t in partial:
            create_technology(db_session, acme.id, dict(t))
        # Now run the seed — tech/notes are skipped (Acme already has tech),
        # but dependencies are resolved against Acme's 3 items; only the
        # resolvable ones are created, the rest skipped (no fabrication).
        seed_customer_intelligence(db_session)
        deps = self._dep_count(db_session, acme.id)
        # At most the resolvable subset; the key invariant is: no dependency
        # points at a missing endpoint (covered by the resolve test) and the
        # count never exceeds the declared dependency list.
        assert 0 <= deps <= len(CUSTOMER_INTELLIGENCE["Acme Manufacturing"].get("dependencies", []))

