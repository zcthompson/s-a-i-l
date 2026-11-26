"""Comment service for collaboration feature.

Enforces customer-scoped access via the central ``sales_access`` policy.
"""

from datetime import UTC, datetime

from sqlalchemy import exists, or_, select
from sqlalchemy.orm import Session

from backend.models.collaboration import Comment, Notification
from backend.models.use_case import CustomerUser, User
from backend.services import email_service
from backend.services.notification_service import notify_user
from backend.services.sales_access import account_read_predicate


class CollaborationService:
    """Business logic for comments, mentions, and notifications."""

    @staticmethod
    def stage_notification(db, user_name, event_type, message, customer_id=None):
        """Insert through the collaboration path, leaving commit/delivery to the caller."""
        notification = Notification(user_name=user_name, type=event_type,
                                    message=message, customer_id=customer_id)
        db.add(notification)
        return notification

    @staticmethod
    def get_comments(db: Session, use_case_id: int) -> list[dict]:
        """Get all comments for a use case, ordered by created_at."""
        comments = (
            db.query(Comment)
            .filter(Comment.use_case_id == use_case_id)
            .order_by(Comment.created_at)
            .all()
        )
        return [c.to_dict() for c in comments]

    @staticmethod
    def get_comment(db: Session, comment_id: int) -> Comment | None:
        """Get a single comment by ID."""
        return db.query(Comment).filter(Comment.id == comment_id).first()

    @staticmethod
    def get_notification(db: Session, notification_id: int) -> Notification | None:
        """Get a single notification by ID."""
        return db.query(Notification).filter(Notification.id == notification_id).first()

    @staticmethod
    def can_modify_comment(comment: Comment, user: dict) -> bool:
        """Only the comment's author or an admin may edit or delete it."""
        if user.get("is_admin") == 1:
            return True
        return comment.user_name == user.get("username")

    @staticmethod
    def create_comment(
        db: Session,
        use_case_id: int,
        user_name: str,
        content: str,
        customer_id: int | None = None,
    ) -> dict:
        """Create a new comment and broadcast via WebSocket."""
        comment = Comment(
            use_case_id=use_case_id,
            user_name=user_name,
            content=content,
        )
        db.add(comment)
        db.commit()
        db.refresh(comment)

        # Parse @mentions and create local notifications — existing users
        # only, so no dead notifications are created for non-usernames.
        mentions = CollaborationService._parse_mentions(content)
        mention_rows: list[Notification] = []
        for mention in mentions:
            mentioned = db.query(User).filter(User.username == mention).first()
            if not mentioned:
                continue
            notification = CollaborationService.stage_notification(
                db, mention, "mention",
                f"{user_name} mentioned you in a comment on use case #{use_case_id}", customer_id)
            mention_rows.append(notification)

        db.commit()
        # Per-recipient real-time push for each mention notification.
        for notification in mention_rows:
            db.refresh(notification)
            notify_user(notification.user_name, notification.to_dict())  # type: ignore[arg-type]
            email_service.deliver_notification_email(db, notification)
        return comment.to_dict()

    @staticmethod
    def update_comment(db: Session, comment_id: int, content: str, user_name: str) -> dict | None:
        """Update a comment."""
        comment = db.query(Comment).filter(Comment.id == comment_id).first()
        if not comment:
            return None
        comment.content = content
        comment.updated_at = datetime.now(UTC)
        db.commit()
        db.refresh(comment)
        return comment.to_dict()

    @staticmethod
    def delete_comment(db: Session, comment_id: int) -> bool:
        """Delete a comment."""
        comment = db.query(Comment).filter(Comment.id == comment_id).first()
        if not comment:
            return False
        db.delete(comment)
        db.commit()
        return True

    @staticmethod
    def _parse_mentions(content: str) -> list[str]:
        """Extract @mentions from comment content."""
        import re
        mentions = re.findall(r"@(\w+)", content)
        # Filter out @mentions that are not actual usernames (simple heuristic)
        # In production, this would check against a user database
        return mentions

    @staticmethod
    def get_user_notifications(
        db: Session,
        user_name: str,
        limit: int = 50,
        unread_only: bool = False,
        customer_id: int | None = None,
    ) -> list[dict]:
        """Get notifications for a user with optional customer scoping."""
        # Legacy notification behavior is unchanged; only H5 account-scoped rows
        # require current read access, before pagination is applied.
        task_types = ("task_assigned", "task_reassigned", "task_completed", "task_due_soon", "task_overdue")
        readable = exists(select(User.id).where(User.username == user_name, User.is_active == 1,
                                               account_read_predicate(User, Notification.customer_id)))
        query = db.query(Notification).filter(Notification.user_name == user_name,
            or_(Notification.type.not_in(task_types), Notification.customer_id.is_(None), readable))
        if customer_id is not None:
            query = query.filter(Notification.customer_id == customer_id)
        if unread_only:
            query = query.filter(Notification.read == 0)
        query = query.order_by(Notification.created_at.desc())
        notifications = query.limit(limit).all()
        return [n.to_dict() for n in notifications]

    @staticmethod
    def mark_as_read(db: Session, notification_id: int):
        """Mark a notification as read."""
        notification = db.query(Notification).filter(Notification.id == notification_id).first()
        if notification:
            notification.read = 1
            db.commit()

    @staticmethod
    def broadcast_to_customer(
        db: Session,
        customer_id: int,
        event_type: str,
        message: str,
        exclude_user: str | None = None,
    ) -> list[dict]:
        """Create notification records for every user with READ scope on a
        customer.

        Called when scoring, status changes, or comments occur. Recipients
        (Part 13 DV8) = the customer's junction rows UNION every user the
        central policy grants READ on it (memberships, inside-sales and
        sales-ops assignments, team managers, global readers incl. admins)
        — ONE query, one row per user (deduped by user id). ``exclude_user``
        (usually the actor) is skipped so a user is not notified about
        their own action.
        """

        junction = exists(select(CustomerUser.id).where(
            CustomerUser.user_id == User.id, CustomerUser.customer_id == customer_id))
        records = (
            db.query(User.username, User.email)
            .filter(or_(junction, account_read_predicate(User, customer_id)))
            .order_by(User.id)
            .all()
        )
        created = []
        staged = []
        for (uname, email) in records:
            if exclude_user is not None and uname == exclude_user:
                continue
            notification = CollaborationService.stage_notification(
                db, uname, event_type, message, customer_id)
            created.append(notification.to_dict())
            staged.append((notification, email))
        # Persist the notification rows — callers (scoring, status changes,
        # comments) do not commit afterwards and the request session is
        # closed without a commit, so uncommitted rows would be lost.
        if created:
            db.commit()
            # Per-recipient real-time push: each recipient gets their own
            # notification row over their own sockets (main-loop bridge).
            for row in created:
                notify_user(row["user_name"], row)
            # Email delivery (EL): the settings are read EXACTLY ONCE and the
            # recipient addresses come from the fan-out query itself — the
            # query count is fixed (2 SELECTs) and never scales with the
            # number of recipients (the S6 pin in test_part13_dv_wave1).
            eff = email_service.effective_email_settings(db)
            if email_service.delivery_ready(eff):
                for obj, email in staged:
                    email_service.deliver_notification_email(db, obj, eff=eff, recipient_email=email)
        return created
