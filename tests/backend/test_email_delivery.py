"""Prove notification producer wiring and best-effort SMTP delivery."""

from types import SimpleNamespace

import pytest
from backend.models.collaboration import Comment, Notification
from backend.models.use_case import Customer, CustomerUser, UseCase, User
from backend.services import customer_engagement_service, email_service
from backend.services.collaboration_service import CollaborationService
from backend.services.customer_user_service import CustomerUserService

from tests.backend import test_email_settings

email_defaults = test_email_settings.email_defaults
smtp = test_email_settings.smtp


@pytest.fixture()
def recipient(db_session):
    row = User(username="recipient", email="recipient@example.test", hashed_password="fake", approved=1, is_active=1)
    db_session.add(row)
    db_session.commit()
    return row


@pytest.fixture()
def use_case(db_session):
    """A real use case for the mention tests to comment on.

    The comment table enforces its use_cases foreign key on PostgreSQL
    (SQLite connections run with the pragma off), so the referenced row
    must exist — a bare id would only pass on SQLite.
    """
    row = UseCase(title="Email notification use case")
    db_session.add(row)
    db_session.commit()
    return row


def mention(db, use_case_id):
    return CollaborationService.create_comment(db, use_case_id, "admin", "Hello @recipient")


def test_mention(db_session, recipient, use_case, email_defaults, smtp):
    mention(db_session, use_case.id)
    assert len(smtp.messages) == 1
    msg = smtp.messages[0]
    row = db_session.query(Notification).filter_by(type="mention").one()
    assert msg["To"] == recipient.email
    assert msg["From"] == "sail@example.test"
    assert msg["Subject"] == "S-A-I-L: Mention"
    assert msg.get_content() == f"{row.message}\n\nSent by S-A-I-L (Sales Analytics and Intelligence Launchpad).\n"


@pytest.mark.parametrize("skip", ["disabled", "no_email", "inactive", "missing_user"])
def test_skipped_delivery(db_session, recipient, use_case, email_defaults, smtp, skip):
    if skip == "disabled":
        email_defaults.email_enabled = False
    elif skip == "no_email":
        recipient.email = " "
    elif skip == "inactive":
        recipient.is_active = 0
    else:
        db_session.delete(recipient)
    db_session.commit()
    mention(db_session, use_case.id)
    assert smtp.calls == []


@pytest.mark.parametrize("failure", ["auth", "send", "connection"])
def test_mail_failure_preserves_comment(db_session, recipient, use_case, email_defaults, smtp, failure):
    smtp.failure = failure
    created = mention(db_session, use_case.id)
    db_session.expire_all()
    assert db_session.query(Comment).filter_by(id=created["id"]).one().content == "Hello @recipient"
    assert db_session.query(Notification).filter_by(user_name="recipient").count() == 1
    assert smtp.messages == []
    if failure != "connection":
        assert smtp.calls[-1] == "quit"


def test_broadcast_fanout(db_session, recipient, email_defaults, smtp):
    customer = Customer(name="Email customer")
    db_session.add(customer)
    db_session.flush()
    db_session.add(CustomerUser(customer_id=customer.id, user_id=recipient.id, role="member"))
    db_session.commit()
    created = CollaborationService.broadcast_to_customer(db_session, customer.id, "status_change", "Status changed")
    assert {r["user_name"] for r in created} == {"admin", "recipient"}
    assert len(smtp.messages) == len(created) == 2
    assert {msg["To"] for msg in smtp.messages} == {"admin@test.local", recipient.email}
    assert all(msg["Subject"] == "S-A-I-L: Status changed" for msg in smtp.messages)


def test_sharing(db_session, recipient, email_defaults, smtp):
    customer = Customer(name="Email shared customer")
    db_session.add(customer)
    db_session.commit()
    admin = db_session.query(User).filter_by(username="admin").one()
    CustomerUserService.notify_user_of_sharing(db_session, customer, recipient, admin)
    assert len(smtp.messages) == 1
    assert smtp.messages[0]["Subject"] == "S-A-I-L: Customer shared"
    assert smtp.messages[0]["To"] == recipient.email


def test_task_assignment(db_session, email_defaults, smtp):
    customer = Customer(name="Email task customer")
    db_session.add(customer)
    db_session.commit()
    task = customer_engagement_service.create_task(db_session, customer.id,
        {"title": "Email follow-up", "assignee": "admin"}, "admin")
    assert task["title"] == "Email follow-up"
    assert len(smtp.messages) == 1
    assert smtp.messages[0]["Subject"] == "S-A-I-L: Task assigned"
    assert smtp.messages[0]["To"] == "admin@test.local"


@pytest.mark.parametrize("event,label", list(email_service.TYPE_LABELS.items()) + [("custom", "custom")])
def test_labels(event, label):
    msg = email_service.build_message(SimpleNamespace(type=event, message="Synthetic notification"))
    assert msg["Subject"] == f"S-A-I-L: {label}"


@pytest.mark.parametrize("scenario,status", [("disabled", "skipped_not_configured"),
    ("missing", "skipped_no_recipient_email"), ("sent", "sent"), ("failed", "failed")])
def test_delivery_status(db_session, email_defaults, smtp, scenario, status):
    row = SimpleNamespace(user_name="missing" if scenario == "missing" else "admin", type="mention", message="Hello")
    if scenario == "disabled":
        email_defaults.email_enabled = False
    if scenario == "failed":
        smtp.failure = "send"
    assert email_service.deliver_notification_email(db_session, row) == status
