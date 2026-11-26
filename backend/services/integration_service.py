"""External integration service (Slack, Teams, Jira).

Credentials are resolved as a DB override over .env (the same layering
as inference settings): the UI persists via
the admin-config API into system_config categories
``integration_<platform>``, and the send/status routes honor those
stored values. .env remains the fallback for deployments configured
the classic way.
"""

import os
from typing import Any

import httpx
from sqlalchemy.orm import Session

from backend.config import get_settings
from backend.services.config_service import get_config_values


class IntegrationService:
    """Service for external tool integrations."""

    @staticmethod
    def send_slack_notification(webhook_url: str, message: str, title: str = "S-A-I-L") -> dict[str, Any]:
        """Send a notification to a Slack channel via webhook."""
        if not webhook_url:
            return {"success": False, "error": "No webhook URL configured"}

        payload = {
            "text": f"*{title}*",
            "blocks": [
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": message},
                }
            ],
        }

        try:
            async def _post():
                async with httpx.AsyncClient(timeout=10) as client:
                    response = await client.post(webhook_url, json=payload)
                    return {"success": response.status_code == 200, "status": response.status_code}
            import asyncio
            return asyncio.run(_post())
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    def send_teams_notification(webhook_url: str, message: str, title: str = "S-A-I-L") -> dict[str, Any]:
        """Send a notification to MS Teams via webhook."""
        if not webhook_url:
            return {"success": False, "error": "No webhook URL configured"}

        payload = {
            "@type": "MessageCard",
            "@context": "https://schema.org/extensions",
            "themeColor": "0078D4",
            "summary": title,
            "sections": [{
                "activityTitle": title,
                "activityText": message,
            }],
        }

        try:
            async def _post():
                async with httpx.AsyncClient(timeout=10) as client:
                    response = await client.post(webhook_url, json=payload)
                    return {"success": response.status_code == 200, "status": response.status_code}
            import asyncio
            return asyncio.run(_post())
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    def create_jira_ticket(
        jira_url: str,
        api_key: str,
        project_key: str,
        summary: str,
        description: str,
        issue_type: str = "Task",
    ) -> dict[str, Any]:
        """Create a Jira ticket for a use case."""
        if not jira_url or not api_key:
            return {"success": False, "error": "Jira credentials not configured"}

        payload = {
            "fields": {
                "project": {"key": project_key},
                "summary": summary,
                "description": description,
                "issuetype": {"name": issue_type},
                "customfield_10050": "S-A-I-L",  # Label for tracking
            },
        }

        try:
            async def _post():
                async with httpx.AsyncClient(timeout=10) as client:
                    response = await client.post(
                        f"{jira_url}/rest/api/2/issue",
                        headers={
                            "Authorization": f"Bearer {api_key}",
                            "Content-Type": "application/json",
                        },
                        json=payload,
                    )
                    if response.status_code == 201:
                        data = response.json()
                        return {"success": True, "key": data["key"], "url": f"{jira_url}/browse/{data['key']}"}
                    return {"success": False, "status": response.status_code, "error": response.text}
            import asyncio
            return asyncio.run(_post())
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    def get_effective_integration_settings(db: Session | None) -> dict[str, str]:
        """Resolve integration credentials: stored DB values win, .env
        is the fallback.

        Mirrors ``config_service.effective_inference_settings``: with
        ``db=None`` only .env is consulted; empty/soft-deleted entries
        fall through to .env. Stored keys: ``webhook_url`` (slack,
        teams), ``url`` / ``api_key`` / ``project_key`` (jira).
        """
        slack = get_config_values(db, "integration_slack", ("webhook_url",)) if db else {}
        teams = get_config_values(db, "integration_teams", ("webhook_url",)) if db else {}
        jira = (get_config_values(db, "integration_jira", ("url", "api_key", "project_key"))
                if db else {})
        # The SAIL_-prefixed env names are
        # canonical; the unprefixed legacy names (pre-rename) remain as
        # aliases. Stored values > env.
        env = get_settings()
        legacy = {
            "slack_webhook_url": env.slack_webhook_url or os.environ.get("SLACK_WEBHOOK_URL") or "",
            "teams_webhook_url": env.teams_webhook_url or os.environ.get("TEAMS_WEBHOOK_URL") or "",
            "jira_url": env.jira_url or os.environ.get("JIRA_URL") or "",
            "jira_api_key": env.jira_api_key or os.environ.get("JIRA_API_KEY") or "",
            "jira_project_key": env.jira_project_key or os.environ.get("JIRA_PROJECT_KEY") or "",
        }
        return {
            "slack_webhook_url": slack.get("webhook_url") or legacy["slack_webhook_url"],
            "teams_webhook_url": teams.get("webhook_url") or legacy["teams_webhook_url"],
            "jira_url": jira.get("url") or legacy["jira_url"],
            "jira_api_key": jira.get("api_key") or legacy["jira_api_key"],
            "jira_project_key": jira.get("project_key") or legacy["jira_project_key"],
        }

    @staticmethod
    def get_configured_integrations(db: Session | None = None) -> dict[str, bool]:
        """Check which integrations are configured (stored values > .env)."""
        eff = IntegrationService.get_effective_integration_settings(db)
        return {
            "slack": bool(eff["slack_webhook_url"]),
            "teams": bool(eff["teams_webhook_url"]),
            "jira": bool(eff["jira_url"] and eff["jira_api_key"]),
        }
