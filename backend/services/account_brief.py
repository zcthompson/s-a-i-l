"""Grounded, locally assembled account briefs."""

import re
import unicodedata
from collections import Counter
from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace

from backend.models.customer_technology import CustomerTechnology
from backend.models.sales_access import InsideSalesAssignment, SalesOpsAssignment, SalesReporting
from backend.models.use_case import CustomerUser, User
from backend.services import (
    customer_contact_service,
    customer_engagement_service,
    customer_intelligence,
    deal_service,
    pipeline_read_model,
    sales_note_service,
    sales_personas,
)
from backend.services.customer_access import require_account_read_service


def _md_escape(value):
    value = str(value if value is not None else "not recorded")
    value = ''.join(' ' if unicodedata.category(c).startswith('C') and c != '\0' else c
                    for c in value if c != '\0')
    return re.sub(r'([\\`*_#\[\]<>])', r'\\\1', value)


def _money(value):
    if value is None:
        return 'not recorded'
    value = Decimal(str(value))
    return '$0.00 recorded' if value == 0 else f'${value:,.2f} (USD, source-labelled)'


def sanitize_brief_filename(name, customer_id):
    name = unicodedata.normalize('NFKD', name or '')
    safe = ''.join(c for c in name if c.isascii() and (c.isalnum() or c == ' '))
    safe = re.sub(r'_+', '_', safe.replace(' ', '_'))[:40].strip('_')
    return f'account_brief_{safe or f"customer-{customer_id}"}'


def _display(user):
    return (user.display_name or user.username) if user else None


def _sales_context(db, cid, usernames):
    owners = (db.query(User).join(CustomerUser, CustomerUser.user_id == User.id)
              .filter(CustomerUser.customer_id == cid, CustomerUser.role == 'owner')
              .order_by(CustomerUser.id).all())
    reps = [u for u in owners if u.sales_role == 'rep']
    owner = reps[0] if len(reps) == 1 else (owners[0] if owners else None)
    from sqlalchemy import and_
    users = (db.query(User, SalesReporting.id).outerjoin(
        SalesReporting, and_(SalesReporting.manager_user_id == User.id,
                             SalesReporting.rep_user_id == (owner.id if owner else None)))
        .filter((SalesReporting.id.is_not(None)) | (User.username.in_(usernames)))
        .order_by(SalesReporting.id).all())
    manager = next((u for u, reporting_id in users if reporting_id is not None), None)
    names = {u.username: _display(u) for u, _ in users}
    inside = (db.query(User).join(InsideSalesAssignment, InsideSalesAssignment.inside_sales_user_id == User.id)
              .filter(InsideSalesAssignment.customer_id == cid).order_by(InsideSalesAssignment.id).all())
    ops = (db.query(User).join(SalesOpsAssignment, SalesOpsAssignment.user_id == User.id)
           .filter(SalesOpsAssignment.customer_id == cid).order_by(SalesOpsAssignment.id).all())
    return {'owner': _display(owner), 'manager': _display(manager),
            'inside_sales': [_display(u) for u in inside], 'sales_ops': [_display(u) for u in ops]}, names


def build_account_brief(db, user, customer_id, *, now=None):
    customer = require_account_read_service(db, user, customer_id)
    now = customer_engagement_service.utc(now or datetime.now(UTC))
    generated = now.isoformat()
    tech = db.query(CustomerTechnology).filter_by(customer_id=customer_id).all()
    ranks = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3}
    tech.sort(key=lambda t: (ranks.get(t.business_criticality, 4), t.name, t.id))
    notes = [n for n in sales_note_service.list_sales_notes(db, customer_id) if n.note_date]
    contacts = [c.to_dict() for c in customer_contact_service.list_contacts(db, customer_id)]
    coverage = customer_contact_service.contact_coverage_for(db, customer_id)
    activities = customer_engagement_service.list_activities(db, customer_id)
    tasks = [t for t in customer_engagement_service.list_tasks(db, customer_id)
             if t['status'] in ('open', 'in_progress')]
    usernames = {a['actor'] for a in activities} | {t['assignee'] for t in tasks if t['assignee']}
    context, names = _sales_context(db, customer_id, usernames)
    for activity in activities:
        activity['actor_display'] = names.get(activity['actor'], activity['actor'])
    for task in tasks:
        task['assignee_display'] = names.get(task['assignee'], task['assignee'])
        raw = SimpleNamespace(status=task['status'],
                              due_at=datetime.fromisoformat(task['due_at']) if task['due_at'] else None,
                              due_date=date.fromisoformat(task['due_date']) if task['due_date'] else None)
        task['due'] = customer_engagement_service.render_due(raw) if raw.due_at or raw.due_date else 'not recorded'
        task.update(customer_engagement_service.due_flags(raw, now=now))
    summary = pipeline_read_model.pipeline_summary_for(db, customer_id)
    renewal = pipeline_read_model.renewal_attention_summaries_for(
        db, [customer_id], reference_date=now.date(), as_of=generated)[customer_id]
    opportunities = customer_intelligence.get_account_workspace(db, customer_id)['opportunities']
    personas = [sales_personas.get_persona(p) for p in sales_personas.PERSONA_ORDER
                if p in {c['persona'] for c in contacts}]
    note_items = [{'title': n.title, 'note_date': n.note_date.isoformat(), 'category': n.category,
                   'author': n.author, 'content': n.content[:280].rstrip() + ('…' if len(n.content) > 280 else '')}
                  for n in notes[:5]]
    deals = deal_service.list_deals(db, customer_id)
    sections = {
        'deals': {'available': bool(deals), 'source': 'rep-maintained deals', 'items': deals},
        'account_snapshot': {'available': True, 'source': 'S-A-I-L customer record', 'name': customer.name,
                             'description': customer.description, 'vertical': customer.vertical, **context},
        'technology': {'available': bool(tech), 'source': 'technology inventory',
                       'by_category': dict(sorted(Counter(t.category or 'unknown' for t in tech).items())),
                       'items': [t.to_dict() for t in tech[:15]]},
        'pipeline': {'available': summary['source'] is not None, 'source': 'partner pipeline', 'summary': summary},
        'renewals': {'available': renewal['snapshot'] is not None, 'source': 'partner pipeline', 'attention': renewal},
        'notes': {'available': bool(note_items), 'source': 'sales notes', 'items': note_items},
        'attention': {'available': bool(opportunities), 'source': 'account workspace', 'opportunities': opportunities},
        'contacts': {'available': True, 'source': 'customer contacts', 'items': contacts, 'coverage': coverage},
        'persona_questions': {'available': bool(personas), 'source': 'persona registry', 'personas': personas},
        'engagement': {'available': True, 'source': 'recorded activities and dated notes',
                       'last_contacted': coverage['last_contacted'], 'last_contacted_basis': coverage['last_contacted_basis']},
        'activities': {'available': bool(activities), 'source': 'recorded activities', 'items': activities[:5]},
        'tasks': {'available': bool(tasks), 'source': 'customer tasks', 'items': tasks},
    }
    source = summary['source'] or {}
    brief = {'customer_id': customer_id, 'customer_name': customer.name, 'generated_at': generated,
             'calc_version': 'account-brief/1', 'source_snapshots': {
                 'pipeline_import_id': source.get('import_id'), 'pipeline_source_file': source.get('source_file'),
                 'pipeline_imported_at': source.get('imported_at'), 'technology_recorded': len(tech),
                 'notes_recorded': len(notes), 'contacts_recorded': len(contacts),
                 'activities_recorded': len(activities), 'open_tasks': len(tasks)}, 'sections': sections}
    brief['markdown'] = render_account_brief_markdown(brief)
    return brief


def _citation(source):
    if not source:
        return 'no partner pipeline recorded'
    return (f"partner pipeline import #{source['import_id']} — {_md_escape(source['source_file'])}, "
            f"imported {_md_escape(source['imported_at'])} (imported_at is import time, not a business effective date)")


def _value(value):
    return _md_escape(value if value is not None and str(value).strip() else 'not recorded')


def render_account_brief_markdown(brief):
    s, snap = brief['sections'], brief['source_snapshots']
    lines = [f"# Account Brief — {_value(brief['customer_name'])}", '',
             f"Generated {_value(brief['generated_at'])} · calc account-brief/1 · deterministic (no AI)",
             f"Source snapshots: {_citation(s['pipeline']['summary']['source'])}; "
             f"{snap['technology_recorded']} technologies · {snap['notes_recorded']} notes · "
             f"{snap['contacts_recorded']} contacts · {snap['activities_recorded']} activities · "
             f"{snap['open_tasks']} open tasks (recorded)"]
    headings = [('account_snapshot', 'Account snapshot'), ('technology', 'Technology inventory'),
                ('deals', 'Rep-maintained deals (separate commercial records)'), ('pipeline', 'Vendor-reported pipeline'), ('renewals', 'Renewals (vendor-reported end dates)'),
                ('notes', 'Recent sales notes'), ('attention', 'Attention items'),
                ('contacts', 'Contacts & buying coverage'), ('persona_questions', 'Persona questions'),
                ('engagement', 'Engagement'), ('activities', 'Recorded interactions'), ('tasks', 'Open tasks')]
    for key, heading in headings:
        section = s[key]
        lines.extend(['', f'## {heading}'])
        if not section['available']:
            lines.append('- Not recorded.')
            continue
        add = lines.append
        if key == 'account_snapshot':
            for field in ('name', 'description', 'vertical', 'owner', 'manager', 'inside_sales', 'sales_ops'):
                v = section[field]
                v = ', '.join(v) if isinstance(v, list) else v
                add(f"- {field.replace('_', ' ').capitalize()}: {_value(v)} (S-A-I-L customer record)")
        elif key == 'technology':
            add('- Categories: ' + ', '.join(f'{_value(k)}: {v}' for k, v in section['by_category'].items()) + ' (technology inventory)')
            for item in section['items']:
                fields = ('vendor', 'category', 'version_edition', 'quantity', 'deployment_model', 'lifecycle_state',
                          'support_state', 'business_criticality', 'verification_state', 'source')
                details = '; '.join(f"{f.replace('_', ' ')}: {_value(item.get(f))}" for f in fields)
                observed = f"; observed {_value(item['date_observed'])}" if item['date_observed'] else ''
                add(f"- {_value(item['name'])}: {details} (technology inventory{observed})")
        elif key == 'deals':
            for deal in section['items']:
                amount = deal['amount']
                money = 'amount not recorded' if amount is None else f"{amount['currency']} {amount['minor'] / 100:,.2f} {deal['amount_basis']}"
                add(f"- {_value(deal['name'])}: {deal['stage']['label']}; {money}; close {_value(deal['close_date'])} (rep-maintained deal #{deal['id']})")
        elif key == 'pipeline':
            p = section['summary']
            citation = _citation(p['source'])
            add('- Stages: ' + ', '.join(f'{k}: {p["stages"][k]}' for k in ('open', 'won', 'lost', 'unknown')) + f' ({citation})')
            add('- Grain: ' + ', '.join(f'{k.replace("_", " ")}: {p["grain"][k]}' for k in ('line_count', 'opportunity_count', 'unidentified_lines')) + f' ({citation})')
            for k in ('acv', 'tcv'):
                add(f"- {k.upper()}: {_money(p['amounts'][k]['total'])} ({citation})")
            for k in ('currency_basis', 'currency_note', 'precision_note'):
                if p[k]: add(f"- {_value(p[k])} ({citation})")
        elif key == 'renewals':
            a = section['attention']
            citation = _citation(a['snapshot'])
            add('- Counts: ' + ', '.join(f'{k}: {a["counts"][k]}' for k in ('overdue', 'within_30', 'within_60', 'within_90', 'within_180', 'beyond_180', 'unknown_date')) + f' ({citation})')
            cards = [card for bucket in ('overdue', 'within_30', 'within_60', 'within_90', 'within_180', 'unknown_date') for card in a['buckets'][bucket]][:10]
            for c in cards:
                conflict = f"; conflicting end dates: {_value(', '.join(c['conflicting_end_dates']))}" if c['conflicting_end_dates'] else ''
                add(f"- {_value(c['opportunity_number'])}: {_value(c['opportunity_name'])}; renewal date: {_value(c['renewal_date'])}; days: {_value(c['days'])}; ACV: {_money(c['est_acv']['total'])}; TCV: {_money(c['est_tcv']['total'])}; reported renewal: {c['reported_renewal']}{conflict} ({citation})")
            add(f"- {_value(a['note'])} ({citation})")
        elif key == 'notes':
            for n in section['items']:
                add(f"- {_value(n['title'])}; {_value(n['category'])}: {_value(n['content'])} (sales note {_value(n['note_date'])} by {_value(n['author'])})")
        elif key == 'attention':
            add('Deterministic synthesis from the account workspace — each item cites its evidence; items are observations, not commitments.')
            for o in section['opportunities']:
                e = o['evidence']
                add(f"- {_value(o['severity'])}; {_value(o['type'])}; {_value(o['title'])}: {_value(o['detail'])} ({_value(e['source'])}: {_value(e['source_name'])})")
        elif key == 'contacts':
            for c in section['items']:
                roles = ', '.join(r['role'] for r in c['buying_roles'])
                add(f"- {_value(c['display_name'])}; title: {_value(c['title'])}; persona: {_value(c['persona_label'])}; buying roles: {_value(roles)} (customer contacts)")
            add('Coverage gaps (prompts to record — not evidence of absence):')
            for gap in section['coverage']['gaps']: add(f'- {_value(gap)}')
        elif key == 'persona_questions':
            for p in section['personas']:
                add(f"- {_value(p['label'])} (persona registry — {_value(p['label'])})")
                for q in p['question_base']: add(f"- ? {_value(q)} (persona registry — {_value(p['label'])})")
        elif key == 'engagement':
            add(f"- {_value(section['last_contacted_basis'])}")
        elif key == 'activities':
            for a in section['items']:
                when = datetime.fromisoformat(a['occurred_at']).astimezone(UTC).strftime('%Y-%m-%d %H:%M UTC') if a['occurred_at'] else a['occurred_date']
                add(f"- {_value(a['type'])}; {_value(when)}; actor: {_value(a['actor_display'])}; outcome: {_value(a['outcome'])} (recorded activity)")
        elif key == 'tasks':
            for t in section['items']:
                flag = ' [overdue]' if t['overdue'] else ' [due soon]' if t['due_soon'] else ''
                add(f"- {_value(t['title'])}; {_value(t['status'])}; assignee: {_value(t['assignee_display'])}; due: {_value(t['due'])}{flag} (customer task)")
    return '\n'.join(lines) + '\n'
