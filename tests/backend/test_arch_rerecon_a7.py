"""Batch-query pins — per-row queries on list surfaces batched (the four
surfaces named in the audit findings).

Each pin records the SQL statement families executed by the surface and
shows the family count is CONSTANT as the row count grows (was one query
per row / per batch before the batch).

Run: pytest tests/backend/test_arch_rerecon_a7.py -v
"""

import os
from datetime import UTC, datetime, timedelta

from sqlalchemy import event

os.environ.setdefault("SAIL_JWT_SECRET", "test-secret-for-unit-tests-only-00000000")


def _record(db_session):
    engine = db_session.get_bind()
    engine = getattr(engine, "engine", engine)
    statements: list = []

    def rec(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement.lower())

    return engine, statements, rec


def _families(statements, family):
    return sum(1 for s in statements if family in s)


def _mk_user(db_session, username: str):
    from backend.models.use_case import User
    user = User(username=username, email=f"{username}@test.local", hashed_password="unused",
                display_name=username, department="Sales", is_admin=0, approved=1,
                is_active=1, role="user", sales_role="rep")
    db_session.add(user)
    db_session.flush()
    return user


def _mk_customer(db_session, name: str):
    from backend.models.use_case import Customer
    c = Customer(name=name)
    db_session.add(c)
    db_session.flush()
    return c


class TestUserCustomerAccessBatched:
    def test_list_user_customer_access_fixed_customers_family(self, db_session):
        """customer_user_service.list_user_customer_access: the referenced
        customers resolve in ONE batched query regardless of the number of
        junction rows (was one per row)."""
        from backend.models.use_case import CustomerUser
        from backend.services.customer_user_service import CustomerUserService

        user = _mk_user(db_session, "a7_uca")
        first = _mk_customer(db_session, "A7UCA First")
        db_session.add(CustomerUser(customer_id=first.id, user_id=user.id, role="owner"))
        db_session.commit()

        engine, statements, rec = _record(db_session)

        def run():
            statements.clear()
            event.listen(engine, "before_cursor_execute", rec)
            try:
                return CustomerUserService.list_user_customer_access(
                    db_session, user.id, is_admin=0)
            finally:
                event.remove(engine, "before_cursor_execute", rec)

        rows = run()
        assert len(rows) == 1
        customers_queries = _families(statements, "from customers")
        assert customers_queries == 1

        for i in range(4):
            c = _mk_customer(db_session, f"A7UCA Extra {i}")
            db_session.add(CustomerUser(customer_id=c.id, user_id=user.id, role="member"))
        db_session.commit()
        rows = run()
        assert len(rows) == 5
        assert _families(statements, "from customers") == customers_queries


class TestRvToolsListBatched:
    def _mk_batch(self, db_session, customer):
        from backend.models.rvtools_import import RvToolsImport
        b = RvToolsImport(customer_id=customer.id, file_name=f"a7-{customer.name}.csv",
                          file_sha256="0" * 64, file_data=b"x", host_count=1,
                          vm_count=1, datastore_count=1, license_count=1,
                          created_customer=False, imported_by="a7")
        db_session.add(b)
        db_session.flush()
        return b

    def test_list_imports_fixed_customers_family(self, db_session):
        """rvtools_import_service.list_imports: customer names resolve in
        ONE batched query regardless of the number of batches (was one per
        batch, masked by the identity map)."""
        from backend.services.rvtools_import_service import list_imports

        engine, statements, rec = _record(db_session)

        def run():
            statements.clear()
            event.listen(engine, "before_cursor_execute", rec)
            try:
                return list_imports(db_session)
            finally:
                event.remove(engine, "before_cursor_execute", rec)

        b = self._mk_batch(db_session, _mk_customer(db_session, "A7RV One"))
        db_session.commit()
        rows = run()
        assert any(r["import_id"] == b.id and r["customer_name"] == "A7RV One" for r in rows)
        customers_queries = _families(statements, "from customers")
        assert customers_queries == 1

        for i in range(4):
            self._mk_batch(db_session, _mk_customer(db_session, f"A7RV Two {i}"))
        db_session.commit()
        rows = run()
        assert any(r["import_id"] == b.id for r in rows)
        assert _families(statements, "from customers") == customers_queries


class TestOwnershipReviewBatched:
    def test_list_ownership_review_fixed_memberships_family(self, db_session):
        """membership_service.list_ownership_review: the primary owners of
        ALL review customers resolve in ONE batched query (was one per
        customer)."""
        from backend.models.account_membership import AccountMembership
        from backend.services.membership_service import list_ownership_review

        engine, statements, rec = _record(db_session)

        def run():
            statements.clear()
            event.listen(engine, "before_cursor_execute", rec)
            try:
                return list_ownership_review(db_session)
            finally:
                event.remove(engine, "before_cursor_execute", rec)

        owner = _mk_user(db_session, "a7_owner")
        c1 = _mk_customer(db_session, "A7OR One")
        c1.ownership_status = "needs_review"
        db_session.add(AccountMembership(customer_id=c1.id, user_id=owner.id, role="primary_owner"))
        db_session.commit()
        items = run()
        mine = [i for i in items if i["customer_id"] == c1.id]
        assert mine == [{
            "customer_id": c1.id, "name": "A7OR One",
            "current_owner": "a7_owner", "current_owner_user_id": owner.id,
            "placeholder": True,
        }]
        memberships_queries = _families(statements, "account_memberships")
        assert memberships_queries == 1

        for i in range(4):
            c = _mk_customer(db_session, f"A7OR Two {i}")
            c.ownership_status = "needs_review"
            db_session.add(AccountMembership(customer_id=c.id, user_id=owner.id,
                                             role="primary_owner"))
        db_session.commit()
        items = run()
        assert len([i for i in items if i["name"].startswith("A7OR")]) == 5
        assert _families(statements, "account_memberships") == memberships_queries


class TestTaskNotificationScanBatched:
    def _mk_task(self, db_session, customer, assignee, due_offset_hours=-1):
        from backend.models.customer_engagement import CustomerTask
        t = CustomerTask(customer_id=customer.id, title=f"a7 task {customer.name}",
                         assignee=assignee,
                         due_at=datetime.now(UTC) + timedelta(hours=due_offset_hours),
                         status="open", created_by="a7")
        db_session.add(t)
        db_session.flush()
        return t

    def test_scan_fixed_user_lookup_families(self, db_session):
        """task_notification_evaluator.scan_task_notifications: the assignee
        user + junction + membership context resolves in a FIXED number of
        batched queries regardless of the flagged-task count (was one
        user query per flagged task)."""
        from backend.services.task_notification_evaluator import scan_task_notifications

        assignee = _mk_user(db_session, "a7_assignee")
        c1 = _mk_customer(db_session, "A7TN One")
        self._mk_task(db_session, c1, assignee.username)
        db_session.add(CustomerUserRow(c1.id, assignee.id))
        db_session.commit()

        engine, statements, rec = _record(db_session)

        def run():
            statements.clear()
            event.listen(engine, "before_cursor_execute", rec)
            try:
                return scan_task_notifications(db_session)
            finally:
                event.remove(engine, "before_cursor_execute", rec)

        count = run()
        assert count >= 1  # the overdue task notified (others may exist too)
        # The point of the pin: the user/junction/membership lookups are a
        # FIXED number per scan (batched), not one per flagged task. The
        # exact baseline depends on the service's notification helper
        # lookups — what must hold is constancy under scale.
        baseline = (_families(statements, "from users"),
                    _families(statements, "from customer_user"),
                    _families(statements, "from account_memberships"))
        assert baseline[0] <= 2 and baseline[1] <= 2 and baseline[2] <= 2

        # Scale: 4 more overdue tasks for the same assignee, other customers.
        for i in range(4):
            c = _mk_customer(db_session, f"A7TN Two {i}")
            self._mk_task(db_session, c, assignee.username)
            db_session.add(CustomerUserRow(c.id, assignee.id))
        db_session.commit()
        count = run()
        assert count >= 4  # the first window row dedups, the rest notify
        assert (_families(statements, "from users"),
                _families(statements, "from customer_user"),
                _families(statements, "from account_memberships")) == baseline


def CustomerUserRow(customer_id, user_id):
    from backend.models.use_case import CustomerUser
    return CustomerUser(customer_id=customer_id, user_id=user_id, role="member")
