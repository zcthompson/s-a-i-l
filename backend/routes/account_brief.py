"""Account brief preview and capability-gated downloads."""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from backend.dependencies import get_db
from backend.services import sales_access
from backend.services.account_brief import build_account_brief, sanitize_brief_filename
from backend.services.account_brief_pdf import render_account_brief_pdf
from backend.services.customer_access import require_account_read

router = APIRouter(tags=['account-brief'])


def _read(request, db, customer_id):
    try:
        return require_account_read(request, db, customer_id)
    except HTTPException as exc:
        if exc.status_code == 403:
            raise HTTPException(404, 'Customer not found') from exc
        raise


def _brief(request, db, customer_id, export=False):
    user, _ = _read(request, db, customer_id)
    if export and not sales_access.can(user, db, sales_access.CAP_EXPORT, customer_id):
        raise HTTPException(403, 'Export is not permitted for this customer')
    return build_account_brief(db, user, customer_id)


@router.get('/api/customers/{customer_id}/brief/')
def preview(request: Request, customer_id: int, db: Session = Depends(get_db)):
    return _brief(request, db, customer_id)


@router.get('/api/customers/{customer_id}/brief/download/')
def download(request: Request, customer_id: int, db: Session = Depends(get_db)):
    brief = _brief(request, db, customer_id, export=True)
    filename = sanitize_brief_filename(brief['customer_name'], customer_id)
    return Response(brief['markdown'], media_type='text/markdown; charset=utf-8',
                    headers={'Content-Disposition': f'attachment; filename="{filename}.md"'})


@router.get('/api/customers/{customer_id}/brief/pdf/')
def pdf(request: Request, customer_id: int, db: Session = Depends(get_db)):
    brief = _brief(request, db, customer_id, export=True)
    filename = sanitize_brief_filename(brief['customer_name'], customer_id)
    return Response(render_account_brief_pdf(brief), media_type='application/pdf',
                    headers={'Content-Disposition': f'attachment; filename="{filename}.pdf"'})
