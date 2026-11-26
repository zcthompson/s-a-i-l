"""Account brief grounding, access, rendering and query bounds."""

from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import patch

import pytest
from backend.models.customer_contact import ContactBuyingRole, CustomerContact
from backend.models.customer_engagement import CustomerActivity, CustomerTask
from backend.models.customer_technology import CustomerTechnology
from backend.models.sales_note import SalesNote
from backend.models.use_case import Customer
from backend.services import (
    customer_contact_service,
    customer_engagement_service,
    pipeline_read_model,
)
from backend.services.account_brief import (
    _md_escape,
    _money,
    _sales_context,
    build_account_brief,
    sanitize_brief_filename,
)
from backend.services.account_brief_pdf import render_account_brief_pdf
from fastapi import HTTPException

from tests.backend._shared import add_pipeline_batch
from tests.backend.test_customer_contacts import headers, statements

NOW = datetime(2026, 10, 28, 12, tzinfo=UTC)
ADMIN = {'is_admin': 1, 'username': 'admin'}


@pytest.fixture
def account(db_session):
    row = Customer(name='Synthetic <script>')
    db_session.add(row)
    db_session.commit()
    return row.id


def test_empty_deterministic_and_pdf(db_session, account):
    a = build_account_brief(db_session, ADMIN, account, now=NOW)
    b = build_account_brief(db_session, ADMIN, account, now=NOW)
    assert a['markdown'] == b['markdown']
    assert a['sections']['contacts']['available']
    assert 'No contacts recorded' in a['markdown']
    assert '<script>' not in a['markdown']
    # The honest empty case: 8 unavailable sections including rep-maintained deals; attention still fires
    # (the contact-coverage gap card + discovery cards) and the H4
    # null-basis string is byte-identical.
    assert a['markdown'].count('- Not recorded.') == 8
    assert a['sections']['attention']['available']
    assert 'No contacts recorded; No economic buyer recorded; No champion recorded' in a['markdown']
    assert 'No qualified interaction evidence recorded (editing a contact is not engagement)' in a['markdown']
    assert render_account_brief_pdf(a).startswith(b'%PDF')
    for section in ('technology', 'pipeline', 'renewals', 'notes', 'persona_questions', 'activities', 'tasks'):
        assert not a['sections'][section]['available']


def test_grounded_and_due(db_session, account):
    from backend.models.customer_engagement import CustomerActivity
    from backend.services import sales_personas

    db_session.add_all([
        CustomerTechnology(customer_id=account, name='Synthetic tech', category='compute',
                           verification_state='unverified', date_observed=date(2026, 1, 1),
                           business_criticality='critical', lifecycle_state='eol'),
        SalesNote(customer_id=account, title='# * [x] <script> & co', category='general', content='a' * 300, author='Writer', note_date=date(2026, 1, 2)),
        CustomerTask(customer_id=account, title='Due today', created_by='admin', status='open', due_date=NOW.date()),
        CustomerTask(customer_id=account, title='Finished', created_by='admin', status='completed'),
        CustomerContact(customer_id=account, display_name='Synthetic person', persona='executive'),
        CustomerActivity(customer_id=account, type='call', actor='Writer', created_by='admin',
                         occurred_date=date(2026, 1, 5), outcome='scoping call'),
    ])
    db_session.flush()
    contact = db_session.query(CustomerContact).filter_by(customer_id=account).one()
    db_session.add_all([ContactBuyingRole(contact_id=contact.id, role='economic_buyer'),
                        ContactBuyingRole(contact_id=contact.id, role='champion')])
    customer = db_session.query(Customer).filter_by(id=account).one()
    add_pipeline_batch(db_session, [(customer, [
        {'est_acv_usd': 100, 'est_tcv_usd': 200, 'currency_code': 'EUR',
         'current_contract_end_date': date(2026, 11, 1), 'opportunity_number': 'R1'},
        {'est_acv_usd': 50, 'est_tcv_usd': 100},
    ])])
    db_session.add(SalesNote(customer_id=account, title='Undated note', category='general', content='hidden'))
    db_session.commit()
    result = build_account_brief(db_session, ADMIN, account, now=NOW)
    md = result['markdown']
    assert 'Synthetic tech' in md and 'unverified' in md and 'observed 2026-01-01' in md
    assert '\\<script\\>' in md and 'a' * 280 + '…' in md
    assert 'Due today' in md and '[due soon]' in md and 'Finished' not in md
    assert 'persona registry — Executive' in md
    assert 'economic\\_buyer' in md and 'champion' in md
    assert 'Undated note' not in md
    assert '$150.00 (USD, source-labelled)' in md and '$300.00 (USD, source-labelled)' in md
    assert 'non-USD' in md and 'partner pipeline import' in md
    # S8.C grounding pins (primary integration):
    assert 'actor: Writer' in md and '2026-01-05' in md and 'scoping call' in md
    assert 'Last meaningful interaction 2026-01-05 (recorded activities and dated notes; imports, record edits, and scheduling are not engagement)' in md
    assert 'Synthetic person' in md
    assert 'Coverage gaps (prompts to record — not evidence of absence):' in md
    assert 'No contacts recorded' not in md
    assert f"? {sales_personas.get_persona('executive')['question_base'][0]}" in md
    assert 'within_30: 1' in md and 'renewal date: 2026-11-01' in md and 'days: 4' in md
    assert pipeline_read_model.RENEWAL_NOTE in md
    assert 'Deterministic synthesis from the account workspace' in md
    assert 'high; lifecycle\\_risk; Synthetic tech' in md and '(technology: Synthetic tech)' in md
    assert render_account_brief_pdf(result).startswith(b'%PDF')


def test_authorization_first(db_session, account):
    with patch('backend.services.account_brief._sales_context') as assemble:
        with pytest.raises(HTTPException):
            build_account_brief(db_session, {'is_admin': 0, 'username': 'outsider'}, account, now=NOW)
        assemble.assert_not_called()


def test_query_budgets(db_session, account):
    # The workspace's internal reads and the one authorization read are excluded.
    with patch('backend.services.account_brief.customer_intelligence.get_account_workspace', return_value={'opportunities': []}) as workspace:
        with statements(db_session) as sql:
            build_account_brief(db_session, ADMIN, account, now=NOW)
        assert len(sql) - 1 <= 23
        with statements(db_session) as sql:
            customer_contact_service.list_contacts(db_session, account)
        assert len(sql) == 1
        workspace.assert_called_once()
        from backend.models.sales_access import (
            InsideSalesAssignment,
            SalesOpsAssignment,
            SalesReporting,
        )
        from backend.models.use_case import CustomerUser, User

        customer = db_session.query(Customer).filter_by(id=account).one()
        rep = User(username='budget_rep', sales_role='rep', approved=1, is_active=1)
        manager = User(username='budget_manager', approved=1, is_active=1)
        inside = User(username='budget_inside', approved=1, is_active=1)
        ops = User(username='budget_ops', approved=1, is_active=1)
        db_session.add_all([rep, manager, inside, ops])
        db_session.flush()
        db_session.add_all([CustomerUser(customer_id=account, user_id=rep.id, role='owner'),
                            SalesReporting(rep_user_id=rep.id, manager_user_id=manager.id),
                            InsideSalesAssignment(customer_id=account, inside_sales_user_id=inside.id),
                            SalesOpsAssignment(customer_id=account, user_id=ops.id)])
        add_pipeline_batch(db_session, [(customer, [{'est_acv_usd': 100, 'current_contract_end_date': date(2026, 11, 1)}])])
        db_session.add_all([
            CustomerContact(customer_id=account, display_name='Synthetic'),
            CustomerTechnology(customer_id=account, name='Synthetic tech', category='compute'),
            SalesNote(customer_id=account, title='Note', category='general', content='Evidence', note_date=NOW.date()),
            CustomerActivity(customer_id=account, type='call', actor='admin', created_by='admin', occurred_date=NOW.date()),
            CustomerTask(customer_id=account, title='Task', assignee='admin', created_by='admin'),
        ])
        db_session.commit()
        workspace.reset_mock()
        with statements(db_session) as sql:
            build_account_brief(db_session, ADMIN, account, now=NOW)
        assert len(sql) - 1 <= 28
        workspace.assert_called_once()
        for fn, limit in [(customer_contact_service.list_contacts, 5),
                          (customer_contact_service.contact_coverage_for, 4),
                          (customer_engagement_service.list_activities, 3),
                          (customer_engagement_service.list_tasks, 3),
                          (pipeline_read_model.pipeline_summary_for, 3)]:
            with statements(db_session) as sql:
                fn(db_session, account)
            assert len(sql) <= limit
            if fn is customer_contact_service.contact_coverage_for:
                assert len(sql) == 4
        with statements(db_session) as sql:
            _sales_context(db_session, account, {"admin"})
        assert len(sql) == 4
        with statements(db_session) as sql:
            pipeline_read_model.renewal_attention_summaries_for(db_session, [account])
        assert len(sql) <= 3


@pytest.mark.parametrize(('value', 'expected'), [(None, 'not recorded'), (Decimal('0'), '$0.00 recorded'), (Decimal('1234.5'), '$1,234.50 (USD, source-labelled)')])
def test_money(value, expected):
    assert _money(value) == expected


def test_escape_and_filename():
    assert _md_escape('# * [x] <script>\\\n') == r'\# \* \[x\] \<script\>\\ '
    assert sanitize_brief_filename('../../etc', 1) == 'account_brief_etc'
    assert sanitize_brief_filename('A..B', 1) == 'account_brief_AB'
    assert sanitize_brief_filename('<>', 1) == 'account_brief_customer-1'
    assert len(sanitize_brief_filename('a' * 200, 1).removeprefix('account_brief_')) == 40


def test_routes(client, account):
    path = f'/api/customers/{account}/brief/'
    assert client.get(path).status_code == 401
    assert client.get(path, headers=headers()).status_code == 200
    for suffix, ext in [('download/', 'md'), ('pdf/', 'pdf')]:
        response = client.get(path + suffix, headers=headers())
        assert response.status_code == 200
        assert response.headers['content-disposition'] == f'attachment; filename="account_brief_Synthetic_script.{ext}"'


def test_route_access_matrix(client, db_session, account):
    from backend.models.account_membership import AccountMembership
    from backend.models.use_case import CustomerUser, User

    specs = [('owner', 'rep', 'owner'), ('member', None, 'member'),
             ('auditor', 'auditor', 'auditor'), ('sales_admin', 'sales_admin', None),
             ('inside', 'inside_sales', None), ('outsider', None, None)]
    for name, sales_role, role in specs:
        user = User(username='brief_' + name, sales_role=sales_role, approved=1, is_active=1)
        db_session.add(user)
        db_session.flush()
        if role:
            db_session.add(CustomerUser(customer_id=account, user_id=user.id, role=role))
        if name == 'inside':
            db_session.add(AccountMembership(customer_id=account, user_id=user.id, role='inside_sales',
                                             section_grants={'notes': 'contribute'}))
    db_session.commit()
    for name, preview, export in [('owner', 200, 200), ('member', 200, 200),
                                  ('auditor', 200, 200), ('sales_admin', 200, 403),
                                  ('inside', 200, 403), ('outsider', 404, 404)]:
        for suffix, status in [('', preview), ('download/', export), ('pdf/', export)]:
            response = client.get(f'/api/customers/{account}/brief/{suffix}', headers=headers('brief_' + name))
            assert response.status_code == status, (name, suffix, response.text)
            if status == 403:
                assert response.json()['detail'] == 'Export is not permitted for this customer'
            missing = client.get(f'/api/customers/999999/brief/{suffix}', headers=headers('brief_' + name))
            assert missing.status_code == 404


def test_source_scan():
    from pathlib import Path

    assert all('customer_brief' not in path.read_text() for path in Path('backend/routes').glob('*.py'))


def test_workspace_consistency_and_generated_time(db_session, account):
    from datetime import timedelta

    from backend.services.customer_intelligence import get_account_workspace

    first = build_account_brief(db_session, ADMIN, account, now=NOW)
    assert first['sections']['attention']['opportunities'] == get_account_workspace(db_session, account)['opportunities']
    later = build_account_brief(db_session, ADMIN, account, now=NOW + timedelta(days=1))
    first_lines = first['markdown'].splitlines()
    later_lines = later['markdown'].splitlines()
    assert [line for line in first_lines if not line.startswith('Generated ')] == [
        line for line in later_lines if not line.startswith('Generated ')]
