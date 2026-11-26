"""External integration routes (Slack, Teams, Jira).

Status requires authentication; sending messages and creating tickets
requires administrator privileges.
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from backend.auth import get_user_from_request
from backend.dependencies import get_db
from backend.schemas.integrations import (
    JiraCreateTicket,
    SlackSendMessage,
    TeamsSendMessage,
)
from backend.services.integration_service import IntegrationService

router = APIRouter(prefix="/api/integrations", tags=["integrations"])


def _require_user(request: Request) -> dict:
    user = get_user_from_request(request)
    if not user or not user.get("username"):
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


def _require_admin(request: Request) -> dict:
    user = _require_user(request)
    if not user.get("is_admin", False):
        raise HTTPException(status_code=403, detail="Admin privileges required")
    return user


@router.get("/status/")
def integration_status(request: Request, db: Session = Depends(get_db)):
    """Check which integrations are configured (stored values > .env)."""
    _require_user(request)
    return IntegrationService.get_configured_integrations(db)


@router.post("/slack/send/")
def send_slack(
    message: SlackSendMessage,
    request: Request,
    db: Session = Depends(get_db),
):
    """Send notification to Slack channel (stored webhook > .env)."""
    _require_admin(request)
    eff = IntegrationService.get_effective_integration_settings(db)
    webhook_url = eff.get("slack_webhook_url")
    if not webhook_url:
        raise HTTPException(status_code=400, detail="Slack webhook not configured")

    result = IntegrationService.send_slack_notification(
        webhook_url, message.message, message.title or "S-A-I-L"
    )
    if not result.get("success"):
        raise HTTPException(status_code=500, detail="Slack request failed")
    return {"success": True}


@router.post("/teams/send/")
def send_teams(
    message: TeamsSendMessage,
    request: Request,
    db: Session = Depends(get_db),
):
    """Send notification to MS Teams channel (stored webhook > .env)."""
    _require_admin(request)
    eff = IntegrationService.get_effective_integration_settings(db)
    webhook_url = eff.get("teams_webhook_url")
    if not webhook_url:
        raise HTTPException(status_code=400, detail="Teams webhook not configured")

    result = IntegrationService.send_teams_notification(
        webhook_url, message.message, message.title or "S-A-I-L"
    )
    if not result.get("success"):
        raise HTTPException(status_code=500, detail="Teams request failed")
    return {"success": True}


@router.post("/jira/create-ticket/")
def create_jira_ticket(
    ticket: JiraCreateTicket,
    request: Request,
    db: Session = Depends(get_db),
):
    """Create a Jira ticket from a use case (stored credentials > .env)."""
    _require_admin(request)
    eff = IntegrationService.get_effective_integration_settings(db)
    jira_url = eff.get("jira_url")
    api_key = eff.get("jira_api_key")

    if not jira_url or not api_key:
        raise HTTPException(status_code=400, detail="Jira not configured")

    project_key = ticket.project_key or eff.get("jira_project_key")
    if not project_key:
        raise HTTPException(status_code=400, detail="Jira project key required")

    result = IntegrationService.create_jira_ticket(
        jira_url, api_key, project_key,
        ticket.summary, ticket.description, ticket.issue_type or "Task",
    )
    if not result.get("success"):
        raise HTTPException(status_code=500, detail="Jira request failed")
    return result
