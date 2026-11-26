"""Comment + notification routes for collaboration.

Security (2026-08-22 collaboration audit):
- every route requires a valid JWT (401 otherwise);
- access is enforced through the central policy (``sales_access.can``:
  CAP_READ to read, CAP_NOTES + CAP_EDIT to write; admins bypass);
- the comment author is the authenticated user, so the client-supplied
  ``user_name`` is ignored (no impersonation);
- a user can only read or mark their own notifications (admin bypass);
- posting a comment notifies every other user with READ scope on the use
  case's customer (customer-level notification), in addition to @mentions;
- 404-first: a use case or comment whose customer is outside the
  caller's read scope returns the same 404 as a missing one; in-scope
  capability denials keep their exact 403.
"""


from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from backend.auth import get_user_from_request
from backend.dependencies import get_db
from backend.models.use_case import UseCase
from backend.schemas.collaboration import (
    CommentCreate,
    CommentResponse,
    NotificationResponse,
)
from backend.schemas.collaboration import (
    CommentUpdate as CommentUpdateSchema,
)
from backend.services import sales_access
from backend.services.collaboration_service import CollaborationService
from backend.services.notification_service import connection_manager, send_notification
from backend.services.use_case_service import UseCaseService

router = APIRouter(prefix="/api/use-cases", tags=["collaboration"])


def _require_user(request: Request) -> dict:
    user = get_user_from_request(request)
    if not user or not user.get("username"):
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


def _can_access_customer(user: dict, db: Session, customer_id: int | None) -> bool:
    """Read access: the central policy's CAP_READ (admin is
    handled by ``can``)."""
    return sales_access.can(user, db, sales_access.CAP_READ, customer_id)


def _use_case_in_scope_or_404(db: Session, user: dict, use_case_id: int) -> UseCase:
    """The use case if it exists and its customer is in the caller's read
    scope (``_can_access_customer``, unchanged); else the same 404."""
    use_case = _get_use_case_or_404(db, use_case_id)
    if not _can_access_customer(user, db, use_case.customer_id):
        raise HTTPException(status_code=404, detail="Use case not found")
    return use_case


def _can_write_customer(user: dict, db: Session, customer_id: int | None) -> bool:
    """Write access: the central policy's CAP_NOTES (admin is
    handled by ``can``)."""
    return sales_access.can(user, db, sales_access.CAP_NOTES, customer_id)


def _require_edit(user: dict, db: Session, customer_id: int | None) -> None:
    """403 unless the caller holds CAP_EDIT on the customer (auditor is read-only)."""
    if not sales_access.can(user, db, sales_access.CAP_EDIT, customer_id):
        raise HTTPException(status_code=403, detail="Not authorized to modify this customer")


def _get_use_case_or_404(db: Session, use_case_id: int) -> UseCase:
    use_case = UseCaseService.get_by_id(db, use_case_id)
    if not use_case:
        raise HTTPException(status_code=404, detail="Use case not found")
    return use_case


@router.get("/{use_case_id}/comments/", response_model=list[CommentResponse])
def get_comments(
    use_case_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """Get all comments for a use case (junction-scoped, 404-first)."""
    user = _require_user(request)
    _use_case_in_scope_or_404(db, user, use_case_id)
    return CollaborationService.get_comments(db, use_case_id)


@router.post("/{use_case_id}/comments/", response_model=CommentResponse, status_code=201)
async def create_comment(
    use_case_id: int,
    comment: CommentCreate,
    request: Request,
    db: Session = Depends(get_db),
):
    """Create a comment. The author is the authenticated user — the
    client-supplied ``user_name`` is ignored."""
    user = _require_user(request)
    use_case = _use_case_in_scope_or_404(db, user, use_case_id)
    if not _can_write_customer(user, db, use_case.customer_id):
        raise HTTPException(status_code=403, detail="commenting requires note access to this customer")
    _require_edit(user, db, use_case.customer_id)
    result = CollaborationService.create_comment(
        db, use_case_id, user["username"], comment.content, use_case.customer_id
    )
    # Customer-level notification for every other in-scope reader of the
    # customer (central READ scope)
    if use_case.customer_id:
        CollaborationService.broadcast_to_customer(
            db,
            use_case.customer_id,
            "comment_added",
            f"{user['username']} commented on use case '{use_case.title}'.",
            exclude_user=user["username"],
        )
    await send_notification(
        event_type="comment_added",
        data={"use_case_id": use_case_id},
        use_case_id=str(use_case_id),
    )
    return result


@router.put("/comments/{comment_id}/", response_model=CommentResponse)
def update_comment(
    comment_id: int,
    comment: CommentUpdateSchema,
    request: Request,
    db: Session = Depends(get_db),
):
    """Update a comment (author or admin only; 404-first)."""
    user = _require_user(request)
    existing = CollaborationService.get_comment(db, comment_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Comment not found")
    use_case = UseCaseService.get_by_id(db, existing.use_case_id)
    if use_case is not None and not _can_access_customer(user, db, use_case.customer_id):
        raise HTTPException(status_code=404, detail="Comment not found")
    if not CollaborationService.can_modify_comment(existing, user):
        raise HTTPException(status_code=403, detail="Only the author or an admin can edit this comment")
    if use_case is not None and not _can_write_customer(user, db, use_case.customer_id):
        raise HTTPException(status_code=403, detail="No write access to this customer's use case")
    if use_case is not None:
        _require_edit(user, db, use_case.customer_id)
    return CollaborationService.update_comment(db, comment_id, comment.content, user["username"])


@router.delete("/comments/{comment_id}/", status_code=204)
def delete_comment(
    comment_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """Delete a comment (author or admin only; 404-first)."""
    user = _require_user(request)
    existing = CollaborationService.get_comment(db, comment_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Comment not found")
    use_case = UseCaseService.get_by_id(db, existing.use_case_id)
    if use_case is not None and not _can_access_customer(user, db, use_case.customer_id):
        raise HTTPException(status_code=404, detail="Comment not found")
    if not CollaborationService.can_modify_comment(existing, user):
        raise HTTPException(status_code=403, detail="Only the author or an admin can delete this comment")
    if use_case is not None and not _can_write_customer(user, db, use_case.customer_id):
        raise HTTPException(status_code=403, detail="No write access to this customer's use case")
    if use_case is not None:
        _require_edit(user, db, use_case.customer_id)
    CollaborationService.delete_comment(db, comment_id)


@router.get("/notifications/health/", response_model=dict)
def notification_health(request: Request):
    """Check notification service status."""
    _require_user(request)
    return {
        "connected": True,
        "active_connections": connection_manager.connection_count,
    }


@router.get("/notifications/", response_model=list[NotificationResponse])
def get_notifications(
    request: Request,
    limit: int = Query(50, ge=1, le=1000),
    unread_only: bool = Query(False),
    customer_id: int | None = Query(None),
    db: Session = Depends(get_db),
):
    """Get the caller's own notifications (own only; a customer filter is
    junction-checked)."""
    user = _require_user(request)
    if customer_id is not None and not _can_access_customer(user, db, customer_id):
        # 404-first: an out-of-scope filter is the same as a missing
        # customer — it must not confirm the customer exists.
        raise HTTPException(status_code=404, detail="Customer not found")
    return CollaborationService.get_user_notifications(
        db, user["username"], limit, unread_only, customer_id
    )


@router.post("/notifications/{notification_id}/read/", status_code=204)
def mark_notification_read(
    notification_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """Mark the caller's notification as read (owner or admin only;
    404-first — someone else's notification is the same 404 as a
    missing one, so a by-id probe cannot confirm its existence)."""
    user = _require_user(request)
    notification = CollaborationService.get_notification(db, notification_id)
    if notification is None or (
        notification.user_name != user["username"] and user.get("is_admin") != 1
    ):
        raise HTTPException(status_code=404, detail="Notification not found")
    CollaborationService.mark_as_read(db, notification_id)
