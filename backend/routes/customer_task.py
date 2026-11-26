"""Thin account-scoped task routes; assignment grants no account access."""

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from backend.dependencies import get_db
from backend.models.customer_engagement import CustomerTask
from backend.models.use_case import User
from backend.routes.customer_activity import accessible_item, require_write
from backend.routes.customer_contact import _read, _require_user
from backend.schemas.engagement import TaskCreate, TaskDelete, TaskPromotion, TaskUpdate
from backend.services import customer_engagement_service as service
from backend.services import sales_access
from backend.services.customer_access import read_or_404

router = APIRouter(tags=["tasks"])


@router.get("/api/tasks/mine/")
def my_tasks(request: Request, db: Session = Depends(get_db)):
    return service.my_tasks(db, _require_user(request))


@router.get("/api/customers/{customer_id}/tasks/")
def list_tasks(request: Request, customer_id: int, status: str | None = None,
               mine: bool = False, db: Session = Depends(get_db)):
    user, _ = _read(request, db, customer_id)
    return service.list_tasks(db, customer_id, status, user["username"] if mine else None)


@router.post("/api/customers/{customer_id}/tasks/", status_code=201)
def create_task(request: Request, customer_id: int, payload: TaskCreate,
                db: Session = Depends(get_db)):
    user = _require_user(request)
    read_or_404(db, user, customer_id)
    require_write(user, db, customer_id, sales_access.CAP_TASKS, "tasks")
    return service.create_task(db, customer_id, payload.model_dump(), user["username"])


@router.post("/api/customers/{customer_id}/tasks/promote/", status_code=201)
def promote_task(request: Request, response: Response, customer_id: int, payload: TaskPromotion,
                 db: Session = Depends(get_db)):
    user = _require_user(request)
    read_or_404(db, user, customer_id)
    require_write(user, db, customer_id, sales_access.CAP_TASKS, "tasks")
    result = service.promote_task(db, customer_id, payload.model_dump(), user["username"])
    response.status_code = 201 if result["created"] else 200
    return result


@router.get("/api/tasks/{task_id}/")
def get_task(request: Request, task_id: int, db: Session = Depends(get_db)):
    row = accessible_item(_require_user(request), db, CustomerTask, task_id, "Task")
    return service.list_tasks(db, row.customer_id, task_id=row.id)[0]


@router.put("/api/tasks/{task_id}/")
def update_task(request: Request, task_id: int, payload: TaskUpdate,
                db: Session = Depends(get_db)):
    user = _require_user(request)
    row = accessible_item(user, db, CustomerTask, task_id, "Task")
    require_write(user, db, row.customer_id, sales_access.CAP_TASKS, "tasks")
    return service.update_task(db, row, payload.model_dump(exclude_unset=True), user["username"])


@router.delete("/api/tasks/{task_id}/", status_code=204)
def delete_task(request: Request, task_id: int, payload: TaskDelete,
                db: Session = Depends(get_db)):
    user = _require_user(request)
    row = accessible_item(user, db, CustomerTask, task_id, "Task")
    require_write(user, db, row.customer_id, sales_access.CAP_TASKS, "tasks")
    service.delete_task(db, row, payload.expected_version)


@router.get("/api/customers/{customer_id}/workspace-actions/")
def workspace_actions(request: Request, customer_id: int, db: Session = Depends(get_db)):
    """Section write permissions and active, account-authorized assignee choices."""
    user, _ = _read(request, db, customer_id)
    sections = {"contact": (sales_access.CAP_CONTACTS, "contacts"),
                "activity": (sales_access.CAP_ACTIVITIES, "activities"),
                "task": (sales_access.CAP_TASKS, "tasks"),
                "deal": (sales_access.CAP_OPPORTUNITIES, "opportunities"),
                "use_case": (sales_access.CAP_EDIT, None),
                "assessment": (sales_access.CAP_EDIT, None),
                "technology": (sales_access.CAP_EDIT, None),
                "note": (sales_access.CAP_NOTES, "notes"),
                "knowledge": (sales_access.CAP_KNOWLEDGE, None)}
    writable = not sales_access.auditor_read_only(user)
    capabilities = {key: writable and sales_access.can(user, db, cap, customer_id, section=section)
                    for key, (cap, section) in sections.items()}
    assignees = []
    if capabilities["task"] or capabilities["deal"]:
        rows = db.query(User).filter(User.is_active == 1,
            sales_access.account_read_predicate(User, customer_id)).order_by(User.username).all()
        assignees = [{"id": row.id, "username": row.username, "display_name": row.display_name or row.username} for row in rows]
    return {"customer_id": customer_id, "capabilities": capabilities, "assignees": assignees}
