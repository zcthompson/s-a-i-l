"""Tests for IntegrationService (Slack, Teams, Jira webhooks)."""

import os
from unittest.mock import MagicMock, patch

os.environ.setdefault("SAIL_JWT_SECRET", "test-secret-for-unit-tests-only-00000000")

from backend.services.integration_service import IntegrationService

# ── Slack ─────────────────────────────────────────────────────────────────

class TestSlackNotification:
    """Tests for IntegrationService.send_slack_notification()."""

    def test_missing_webhook_url(self):
        """No webhook URL returns an error immediately."""
        result = IntegrationService.send_slack_notification("", "test message")
        assert result["success"] is False
        assert "No webhook URL" in result["error"]

    def test_valid_payload_structure(self):
        """Valid URL produces a payload with correct Slack blocks format."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {}

        with patch("backend.services.integration_service.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post.return_value = mock_response
            result = IntegrationService.send_slack_notification(
                "https://hooks.slack.com/test",
                "Hello world",
                "Test Bot",
            )
            assert result["success"] is True
            assert result["status"] == 200

            # Verify payload structure
            call_args = mock_client.return_value.__aenter__.return_value.post.call_args
            assert call_args[1]["json"]["text"] == "*Test Bot*"
            assert call_args[1]["json"]["blocks"][0]["type"] == "section"
            assert call_args[1]["json"]["blocks"][0]["text"]["type"] == "mrkdwn"

    def test_default_title(self):
        """When title is omitted, defaults to 'S-A-I-L'."""
        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("backend.services.integration_service.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post.return_value = mock_response
            IntegrationService.send_slack_notification("https://hooks.slack.com/test", "msg")
            call_args = mock_client.return_value.__aenter__.return_value.post.call_args
            assert call_args[1]["json"]["text"] == "*S-A-I-L*"

    def test_http_failure(self):
        """Non-200 status code returns failure."""
        mock_response = MagicMock()
        mock_response.status_code = 500

        with patch("backend.services.integration_service.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post.return_value = mock_response
            result = IntegrationService.send_slack_notification(
                "https://hooks.slack.com/test", "msg"
            )
            assert result["success"] is False
            assert result["status"] == 500

    def test_connection_error(self):
        """Network errors are caught and returned as failure."""
        with patch("backend.services.integration_service.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post.side_effect = Exception("Connection refused")
            result = IntegrationService.send_slack_notification(
                "https://hooks.slack.com/test", "msg"
            )
            assert result["success"] is False
            assert "Connection refused" in result["error"]

    def test_message_text_in_payload(self):
        """Message content appears in the mrkdwn text block."""
        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("backend.services.integration_service.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post.return_value = mock_response
            IntegrationService.send_slack_notification(
                "https://hooks.slack.com/test", "Check this: https://example.com"
            )
            call_args = mock_client.return_value.__aenter__.return_value.post.call_args
            assert call_args[1]["json"]["blocks"][0]["text"]["text"] == "Check this: https://example.com"


# ── Teams ─────────────────────────────────────────────────────────────────

class TestTeamsNotification:
    """Tests for IntegrationService.send_teams_notification()."""

    def test_missing_webhook_url(self):
        """No webhook URL returns an error immediately."""
        result = IntegrationService.send_teams_notification("", "test message")
        assert result["success"] is False
        assert "No webhook URL" in result["error"]

    def test_valid_payload_structure(self):
        """Valid URL produces a MessageCard payload."""
        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("backend.services.integration_service.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post.return_value = mock_response
            result = IntegrationService.send_teams_notification(
                "https://outlook.office.com/webhook/test",
                "Score update",
                "S-A-I-L",
            )
            assert result["success"] is True
            assert result["status"] == 200

            call_args = mock_client.return_value.__aenter__.return_value.post.call_args
            payload = call_args[1]["json"]
            assert payload["@type"] == "MessageCard"
            assert payload["@context"] == "https://schema.org/extensions"
            assert payload["summary"] == "S-A-I-L"
            assert payload["sections"][0]["activityTitle"] == "S-A-I-L"

    def test_theme_color(self):
        """MessageCard includes the correct theme color."""
        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("backend.services.integration_service.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post.return_value = mock_response
            IntegrationService.send_teams_notification("https://webhook/test", "msg")
            call_args = mock_client.return_value.__aenter__.return_value.post.call_args
            assert call_args[1]["json"]["themeColor"] == "0078D4"

    def test_http_failure(self):
        """Non-200 status code returns failure."""
        mock_response = MagicMock()
        mock_response.status_code = 404

        with patch("backend.services.integration_service.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post.return_value = mock_response
            result = IntegrationService.send_teams_notification(
                "https://webhook/test", "msg"
            )
            assert result["success"] is False
            assert result["status"] == 404

    def test_connection_error(self):
        """Network errors are caught and returned as failure."""
        with patch("backend.services.integration_service.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post.side_effect = Exception("DNS lookup failed")
            result = IntegrationService.send_teams_notification(
                "https://webhook/test", "msg"
            )
            assert result["success"] is False
            assert "DNS lookup failed" in result["error"]

    def test_activity_text(self):
        """Message appears in activityText section."""
        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("backend.services.integration_service.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post.return_value = mock_response
            IntegrationService.send_teams_notification(
                "https://webhook/test", "Readiness score improved to 85%"
            )
            call_args = mock_client.return_value.__aenter__.return_value.post.call_args
            assert call_args[1]["json"]["sections"][0]["activityText"] == "Readiness score improved to 85%"


# ── Jira ──────────────────────────────────────────────────────────────────

class TestJiraTicket:
    """Tests for IntegrationService.create_jira_ticket()."""

    def test_missing_credentials(self):
        """Missing Jira URL or API key returns error immediately."""
        result = IntegrationService.create_jira_ticket("", "api-key", "PROJ", "Test", "Desc")
        assert result["success"] is False
        assert "Jira credentials" in result["error"]

        result = IntegrationService.create_jira_ticket("https://jira.example.com", "", "PROJ", "Test", "Desc")
        assert result["success"] is False
        assert "Jira credentials" in result["error"]

    def test_successful_creation(self):
        """201 response extracts key and URL from Jira response."""
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {"key": "PROJ-42"}

        with patch("backend.services.integration_service.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post.return_value = mock_response
            result = IntegrationService.create_jira_ticket(
                "https://jira.example.com",
                "test-api-key",
                "PROJ",
                "Implement radar chart",
                "Design a radar chart for score visualization",
                "Story",
            )
            assert result["success"] is True
            assert result["key"] == "PROJ-42"
            assert result["url"] == "https://jira.example.com/browse/PROJ-42"

    def test_payload_structure(self):
        """Payload includes correct Jira fields."""
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {"key": "PROJ-1"}

        with patch("backend.services.integration_service.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post.return_value = mock_response
            IntegrationService.create_jira_ticket(
                "https://jira.example.com",
                "api-key",
                "PROJ",
                "Summary text",
                "Description text",
            )
            call_args = mock_client.return_value.__aenter__.return_value.post.call_args
            payload = call_args[1]["json"]["fields"]
            assert payload["project"]["key"] == "PROJ"
            assert payload["summary"] == "Summary text"
            assert payload["description"] == "Description text"
            assert payload["issuetype"]["name"] == "Task"
            assert payload["customfield_10050"] == "S-A-I-L"

    def test_custom_issue_type(self):
        """Custom issue type is passed through."""
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {"key": "PROJ-1"}

        with patch("backend.services.integration_service.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post.return_value = mock_response
            IntegrationService.create_jira_ticket(
                "https://jira.example.com", "api-key", "PROJ", "Summary", "Desc", "Bug"
            )
            call_args = mock_client.return_value.__aenter__.return_value.post.call_args
            assert call_args[1]["json"]["fields"]["issuetype"]["name"] == "Bug"

    def test_authorization_header(self):
        """Bearer token is sent in Authorization header."""
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {"key": "PROJ-1"}

        with patch("backend.services.integration_service.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post.return_value = mock_response
            IntegrationService.create_jira_ticket(
                "https://jira.example.com", "my-api-key", "PROJ", "Sum", "Desc"
            )
            call_args = mock_client.return_value.__aenter__.return_value.post.call_args
            assert call_args[1]["headers"]["Authorization"] == "Bearer my-api-key"
            assert call_args[1]["headers"]["Content-Type"] == "application/json"

    def test_non_201_failure(self):
        """Non-201 status returns failure with error details."""
        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_response.text = "Forbidden"

        with patch("backend.services.integration_service.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post.return_value = mock_response
            result = IntegrationService.create_jira_ticket(
                "https://jira.example.com", "api-key", "PROJ", "Sum", "Desc"
            )
            assert result["success"] is False
            assert result["status"] == 403
            assert "Forbidden" in result["error"]

    def test_connection_error(self):
        """Network errors are caught and returned as failure."""
        with patch("backend.services.integration_service.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post.side_effect = Exception("Timeout")
            result = IntegrationService.create_jira_ticket(
                "https://jira.example.com", "api-key", "PROJ", "Sum", "Desc"
            )
            assert result["success"] is False
            assert "Timeout" in result["error"]

    def test_api_url_suffix(self):
        """URL is prefixed with /rest/api/2/issue."""
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {"key": "PROJ-1"}

        with patch("backend.services.integration_service.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post.return_value = mock_response
            IntegrationService.create_jira_ticket(
                "https://jira.example.com", "api-key", "PROJ", "Sum", "Desc"
            )
            call_args = mock_client.return_value.__aenter__.return_value.post.call_args
            assert call_args[0][0] == "https://jira.example.com/rest/api/2/issue"


# ── Configured Integrations ───────────────────────────────────────────────

class TestConfiguredIntegrations:
    """Tests for IntegrationService.get_configured_integrations()."""

    def test_all_disabled_by_default(self):
        """With no env vars set, all integrations are disabled."""
        original = dict(os.environ)
        for key in ("SLACK_WEBHOOK_URL", "TEAMS_WEBHOOK_URL", "JIRA_URL", "JIRA_API_KEY"):
            os.environ.pop(key, None)

        try:
            result = IntegrationService.get_configured_integrations()
            assert result == {"slack": False, "teams": False, "jira": False}
        finally:
            os.environ.clear()
            os.environ.update(original)

    def test_slack_enabled(self):
        """When SLACK_WEBHOOK_URL is set, slack is enabled."""
        original = dict(os.environ)
        os.environ["SLACK_WEBHOOK_URL"] = "https://hooks.slack.com/test"
        os.environ.pop("TEAMS_WEBHOOK_URL", None)
        os.environ.pop("JIRA_URL", None)
        os.environ.pop("JIRA_API_KEY", None)

        try:
            result = IntegrationService.get_configured_integrations()
            assert result["slack"] is True
            assert result["teams"] is False
            assert result["jira"] is False
        finally:
            os.environ.clear()
            os.environ.update(original)

    def test_teams_enabled(self):
        """When TEAMS_WEBHOOK_URL is set, teams is enabled."""
        original = dict(os.environ)
        os.environ["TEAMS_WEBHOOK_URL"] = "https://outlook.office.com/test"
        os.environ.pop("SLACK_WEBHOOK_URL", None)
        os.environ.pop("JIRA_URL", None)
        os.environ.pop("JIRA_API_KEY", None)

        try:
            result = IntegrationService.get_configured_integrations()
            assert result["teams"] is True
            assert result["slack"] is False
            assert result["jira"] is False
        finally:
            os.environ.clear()
            os.environ.update(original)

    def test_jira_enabled_both_required(self):
        """Both JIRA_URL and JIRA_API_KEY are required for jira to be enabled."""
        original = dict(os.environ)
        try:
            # Only URL, no key
            os.environ["JIRA_URL"] = "https://jira.example.com"
            os.environ.pop("JIRA_API_KEY", None)
            os.environ.pop("SLACK_WEBHOOK_URL", None)
            os.environ.pop("TEAMS_WEBHOOK_URL", None)
            result = IntegrationService.get_configured_integrations()
            assert result["jira"] is False

            # Only key, no URL
            os.environ.pop("JIRA_URL")
            os.environ["JIRA_API_KEY"] = "test-key"
            result = IntegrationService.get_configured_integrations()
            assert result["jira"] is False

            # Both set
            os.environ["JIRA_URL"] = "https://jira.example.com"
            result = IntegrationService.get_configured_integrations()
            assert result["jira"] is True
            assert result["slack"] is False
            assert result["teams"] is False
        finally:
            os.environ.clear()
            os.environ.update(original)

    def test_all_enabled(self):
        """When all env vars are set, all integrations are enabled."""
        original = dict(os.environ)
        os.environ["SLACK_WEBHOOK_URL"] = "https://hooks.slack.com/test"
        os.environ["TEAMS_WEBHOOK_URL"] = "https://teams.test"
        os.environ["JIRA_URL"] = "https://jira.example.com"
        os.environ["JIRA_API_KEY"] = "key"

        try:
            result = IntegrationService.get_configured_integrations()
            assert result == {"slack": True, "teams": True, "jira": True}
        finally:
            os.environ.clear()
            os.environ.update(original)
