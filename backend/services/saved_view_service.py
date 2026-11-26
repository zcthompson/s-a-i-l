"""Owner-isolated saved filters, with last-writer-wins upserts."""

from datetime import UTC, date, datetime

from fastapi import HTTPException

from backend.models.saved_view import SavedView
from backend.services.dialect_insert import insert_for

ALLOWED_PARAMS = ("q", "vertical", "branch", "owner", "sort", "dir", "page", "ps")
SURFACES = ("portfolio", "account_deals", "account_tasks")
ACCOUNT_PARAMS = {
    "account_deals": {"customer_id", "stage", "owner", "close_from", "close_to", "sort", "layout"},
    "account_tasks": {"customer_id", "view"},
}
NAME_MAX = 100
PARAM_MAX_LEN = 200
SCHEMA_VERSION = 1


def validate_surface(surface):
    if surface not in SURFACES:
        raise HTTPException(422, f"Unknown surface: {surface}")


def validate_params(params, surface="portfolio"):
    if not isinstance(params, dict):
        raise HTTPException(422, "Filter parameters must be a dict")
    result = {}
    for key, value in params.items():
        if key not in ACCOUNT_PARAMS.get(surface, ALLOWED_PARAMS):
            raise HTTPException(422, f"Unknown filter parameter: {key}")
        if value is not None and not isinstance(value, str):
            raise HTTPException(422, "Filter parameter values must be strings or null")
        value = value.strip() if value is not None else None
        if value is not None and len(value) > PARAM_MAX_LEN:
            raise HTTPException(422, "Filter parameter values are limited to 200 characters")
        result[key] = value
    if surface in ACCOUNT_PARAMS:
        if not (result.get("customer_id") or "").isdigit() or not 0 < int(result["customer_id"]) <= 2**63 - 1:
            raise HTTPException(422, "A positive customer_id is required")
        result["customer_id"] = str(int(result["customer_id"]))
        enums = {"view": ("all", "open", "overdue", "mine"), "sort": ("close", "name", "updated"), "layout": ("list", "board")}
        for key, values in enums.items():
            if result.get(key) is not None and result[key] not in values:
                raise HTTPException(422, f"Unknown {key}")
        for key in ("stage", "owner"):
            value = result.get(key)
            if value and (key != "owner" or value != "unassigned") and (not value.isdigit() or int(value) <= 0):
                raise HTTPException(422, f"Invalid {key}")
        for key in ("close_from", "close_to"):
            if result.get(key):
                try:
                    date.fromisoformat(result[key])
                except ValueError as exc:
                    raise HTTPException(422, f"Invalid {key}") from exc
        if result.get("close_from") and result.get("close_to") and result["close_from"] > result["close_to"]:
            raise HTTPException(422, "Close date range is reversed")
    return result


def _item(row):
    return {key: getattr(row, key) for key in (
        "id", "name", "surface", "params", "schema_version", "created_at", "updated_at")}


def list_views(db, user_id, surface, customer_id=None):
    validate_surface(surface)
    return [_item(row) for row in db.query(SavedView).filter_by(
        user_id=user_id, surface=surface).order_by(SavedView.name_norm).all()
            if surface == "portfolio" or row.params.get("customer_id") == str(customer_id)]


def save_view(db, user_id, surface, name, params):
    validate_surface(surface)
    name = name.strip() if isinstance(name, str) else ""
    if not 1 <= len(name) <= NAME_MAX:
        raise HTTPException(422, "View name must be 1-100 characters")
    params = validate_params(params, surface)
    # Atomic conflict handling keeps concurrent inserts within the uniqueness key.
    values = dict(user_id=user_id, surface=surface, name=name,
                  name_norm=(f"{params['customer_id']}:{name.lower()}" if surface in ACCOUNT_PARAMS else name.lower()), params=params, schema_version=2 if surface in ACCOUNT_PARAMS else SCHEMA_VERSION)
    row = db.execute(insert_for(db, SavedView).values(**values).on_conflict_do_nothing(
        index_elements=["user_id", "surface", "name_norm"]).returning(SavedView)).scalar_one_or_none()
    created = row is not None
    if not created:
        row = db.execute(insert_for(db, SavedView).values(**values).on_conflict_do_update(
            index_elements=["user_id", "surface", "name_norm"],
            set_={"params": params, "updated_at": datetime.now(UTC)},
        ).returning(SavedView), execution_options={"populate_existing": True}).scalar_one()
    result = _item(row)
    db.commit()
    return result, created


def delete_view(db, user_id, view_id):
    count = db.query(SavedView).filter_by(id=view_id, user_id=user_id).delete(synchronize_session=False)
    if not count:
        raise HTTPException(404, "View not found")
    db.commit()
