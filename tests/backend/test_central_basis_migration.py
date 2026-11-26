"""Central-basis migration pins — the three legacy-basis surfaces on the central policy.

Surfaces migrated from ``granted_customer_ids`` to ``customer_scope`` /
``can()``:
  - sales-notes read gates (customer list + by-id note);
  - customer-knowledge read gates (list + by-id record);
  - the pipeline-import CREATE response scope (must equal the GET
    /{id}/ detail scope for the same caller).

Effects pinned:
  - a sales_manager with team scope (no junction row) READS notes and
    knowledge where every other surface already reads, and may WRITE
    notes (CAP_NOTES via the manager owner level) where the legacy gate
    made it unreachable;
  - an inside_sales holder with a legacy assignment (no membership, no
    junction) READS notes and knowledge on the assigned account;
  - 404-first oracles are byte-identical (out of scope == missing);
  - create-response totals equal detail-response totals for the same
    caller (no more narrow-scope create vs wide-scope detail);
  - ``granted_customer_ids`` is gone from the resolver (source pin).

Run: pytest tests/backend/test_central_basis_migration.py -v
"""

import os

import pytest

from tests.backend.common import _token

os.environ.setdefault("SAIL_JWT_SECRET", "test-secret-for-unit-tests-only-00000000")

OUTER_404 = "Customer not found"



def _mk_user(db_session, username: str, sales_role: str | None = None, is_admin: int = 0):
    from backend.models.use_case import User
    user = User(username=username, email=f"{username}@test.local", hashed_password="unused",
                display_name=username, department="Sales", is_admin=is_admin, approved=1,
                is_active=1, role="user", sales_role=sales_role)
    db_session.add(user)
    db_session.flush()
    return user


@pytest.fixture()
def world(db_session):
    """A1TeamCo: owned by a1_rep (reports to a1_sm); a1_is holds a legacy
    inside-sales assignment; a1_out owns A1OtherCo (outsider for TeamCo);
    a1_aud is a global auditor; a1_admin is a system admin."""
    from backend.models.sales_access import InsideSalesAssignment, SalesReporting
    from backend.models.use_case import Customer, CustomerUser

    team, other = Customer(name="A1TeamCo"), Customer(name="A1OtherCo")
    db_session.add_all([team, other])
    db_session.flush()
    rep = _mk_user(db_session, "a1_rep", "rep")
    sm = _mk_user(db_session, "a1_sm", "sales_manager")
    isales = _mk_user(db_session, "a1_is", "inside_sales")
    aud = _mk_user(db_session, "a1_aud", "auditor")
    admin = _mk_user(db_session, "a1_admin", is_admin=1)
    out = _mk_user(db_session, "a1_out", "rep")
    db_session.add_all([
        CustomerUser(customer_id=team.id, user_id=rep.id, role="owner"),
        CustomerUser(customer_id=other.id, user_id=out.id, role="owner"),
        SalesReporting(rep_user_id=rep.id, manager_user_id=sm.id),
        InsideSalesAssignment(customer_id=team.id, inside_sales_user_id=isales.id),
    ])
    db_session.commit()
    return {"team": team.id, "other": other.id}


def _note(client, world, username, customer_id=None, payload=None):
    """Create a sales note as ``username`` and return (status, body)."""
    if customer_id is None:
        customer_id = world["team"]
    body = payload or {"category": "opportunity", "title": "a1 note", "content": "a1 pin note", "note_date": "2026-11-01"}
    h = _token(username)
    out = client.post(f"/api/customers/{customer_id}/sales-notes/", json=body, headers=h)
    return out


def _same_404(client, username, method, url, missing_url, **kwargs):
    h = _token(username)
    out = getattr(client, method)(url, headers=h, **kwargs)
    miss = getattr(client, method)(missing_url, headers=h, **kwargs)
    assert out.status_code == miss.status_code == 404, (out.status_code, out.text[:160])
    assert out.json() == miss.json()
    return out


class TestSalesNotesCentralBasis:
    def test_manager_team_scope_reads_and_writes_notes(self, client, world):
        """a1_sm has NO junction row; the legacy gate 404'd, the central
        basis (customer_scope + manager owner level in can()) reads and
        writes."""
        h = _token("a1_sm")
        listed = client.get(f"/api/customers/{world['team']}/sales-notes/", headers=h)
        assert listed.status_code == 200

        created = _note(client, world, "a1_sm")
        assert created.status_code == 201, created.text[:200]
        note_id = created.json()["id"]
        got = client.get(f"/api/sales-notes/{note_id}/", headers=h)
        assert got.status_code == 200

    def test_inside_sales_assignment_reads_notes(self, client, world):
        """a1_is holds only a legacy inside-sales assignment: scope reads
        the account; the write gate (CAP_NOTES, unsectioned member level)
        allows notes per the central policy."""
        h = _token("a1_is")
        listed = client.get(f"/api/customers/{world['team']}/sales-notes/", headers=h)
        assert listed.status_code == 200, listed.text[:200]

    def test_outsider_404_first_oracle(self, client, world):
        """Out-of-scope == missing: a1_out cannot read TeamCo's notes and
        gets the byte-identical 404 as a nonexistent customer."""
        created = _note(client, world, "a1_rep")
        assert created.status_code == 201
        note_id = created.json()["id"]
        _same_404(client, "a1_out", "get", f"/api/sales-notes/{note_id}/",
                  f"/api/sales-notes/{note_id + 9000}/")
        _same_404(client, "a1_out", "get", f"/api/customers/{world['team']}/sales-notes/",
                  f"/api/customers/{world['team'] + 9000}/sales-notes/")

    def test_auditor_reads_notes(self, client, world):
        """Global auditor: reads-all is unchanged (was granted, still
        granted)."""
        created = _note(client, world, "a1_rep")
        assert created.status_code == 201
        h = _token("a1_aud")
        assert client.get(f"/api/sales-notes/{created.json()['id']}/", headers=h).status_code == 200
        # app-wide write block still denies the auditor's write (403, not
        # the central gate — the middleware runs first).
        denied = client.post(f"/api/customers/{world['team']}/sales-notes/",
                             json={"category": "opportunity", "title": "x", "content": "x", "note_date": "2026-11-01"},
                             headers=h)
        assert denied.status_code == 403

    def test_admin_preserved(self, client, world):
        created = _note(client, world, "a1_rep")
        assert created.status_code == 201
        h = _token("a1_admin", is_admin=True)
        assert client.get(f"/api/sales-notes/{created.json()['id']}/", headers=h).status_code == 200


class TestCustomerKnowledgeCentralBasis:
    def _mk_entry(self, client, world, username):
        h = _token(username)
        out = client.post(
            "/api/customer-knowledge/",
            files={"file": ("a1note.md", b"# A-1 pin doc\n", "text/markdown")},
            data={"customer_id": str(world["team"])},
            headers=h,
        )
        return out

    def test_manager_team_scope_reads_knowledge(self, client, world):
        created = self._mk_entry(client, world, "a1_rep")
        assert created.status_code in (200, 201), created.text[:200]
        kid = created.json()["knowledge_id"]
        h = _token("a1_sm")
        assert client.get(f"/api/customer-knowledge/{kid}", headers=h).status_code == 200
        listed = client.get(f"/api/customer-knowledge/?customer_id={world['team']}", headers=h)
        assert listed.status_code == 200
        assert any(e["id"] == kid for e in listed.json())

    def test_inside_sales_assignment_reads_knowledge(self, client, world):
        created = self._mk_entry(client, world, "a1_rep")
        assert created.status_code in (200, 201), created.text[:200]
        h = _token("a1_is")
        assert client.get(f"/api/customer-knowledge/{created.json()['knowledge_id']}",
                          headers=h).status_code == 200

    def test_outsider_404_first_oracle(self, client, world):
        created = self._mk_entry(client, world, "a1_rep")
        assert created.status_code in (200, 201)
        kid = created.json()["knowledge_id"]
        _same_404(client, "a1_out", "get", f"/api/customer-knowledge/{kid}",
                  f"/api/customer-knowledge/{kid + 9000}")
        # explicit out-of-scope customer_id on the list == missing customer
        out = client.get(f"/api/customer-knowledge/?customer_id={world['team']}", headers=_token("a1_out"))
        assert out.status_code == 404
        assert out.json()["detail"] == OUTER_404


class TestPipelineImportCreateEqualsDetail:
    def test_create_response_totals_equal_detail_totals(self, client, world, db_session):
        """The manager's CREATE response previously computed totals on the
        narrower granted_customer_ids basis; now both use customer_scope
        and must be byte-identical per-customer."""
        import csv
        import io

        from backend.models.use_case import Customer
        name = db_session.query(Customer).filter(Customer.id == world["team"]).first().name
        header = ["Customer Account", "Opportunity Name", "Opp Stage",
                  "Est. ACV Line Amount (USD)", "Est. TCV Line Amount (USD)",
                  "Product Offering Group", "Close Date", "Partner Account",
                  "FLAG - Growth / Risk", "Opportunity Currency Code"]
        rows = [[name, "opp-a", "qualified", "10000", "50000", "RHEL",
                 "2026-12-01", "Partner One", "growth", "USD"]]
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(header)
        w.writerows(rows)
        h = _token("a1_sm")
        out = client.post(
            "/api/intelligence-import/",
            files={"file": ("a1-pipeline.csv", buf.getvalue().encode(), "text/csv")},
            headers=h,
        )
        assert out.status_code in (200, 201), out.text[:300]
        created = out.json()
        batch_id = created["import_id"]
        detail = client.get(f"/api/intelligence-import/{batch_id}/", headers=h).json()
        assert created["matched"] == detail["matched"]
        # the manager's team customer IS in the create response (the legacy
        # basis would have excluded it — the exact reported defect)
        assert any(m["customer_name"] == name for m in created["matched"])


class TestLegacyBasisRemoved:
    def test_granted_customer_ids_gone_from_resolver(self):
        import inspect

        from backend.services import sales_access

        src = inspect.getsource(sales_access)
        assert "def granted_customer_ids" not in src
        assert not hasattr(sales_access, "granted_customer_ids")
