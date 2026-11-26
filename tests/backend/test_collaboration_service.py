"""Unit tests for CollaborationService (comments, mentions, notifications, broadcasting)."""

import os

os.environ.setdefault("SAIL_JWT_SECRET", "test-secret-for-unit-tests-only-00000000")

from unittest.mock import Mock, patch

import pytest
from backend.models.collaboration import Comment, Notification
from backend.services.collaboration_service import CollaborationService


def make_query_mock():
    """Create a chainable mock query object for notification tests."""
    from unittest.mock import MagicMock
    q = MagicMock()
    q.filter.return_value = q
    q.order_by.return_value = q
    q.limit.return_value = q
    return q

class TestParseMentions:
    """Test _parse_mentions — extract @mentions from comment content."""

    def test_no_mentions(self):
        result = CollaborationService._parse_mentions("This is a comment")
        assert result == []

    def test_single_mention(self):
        result = CollaborationService._parse_mentions("Hey @john, can you review this?")
        assert result == ["john"]

    def test_multiple_mentions(self):
        result = CollaborationService._parse_mentions("@alice @bob @charlie please review")
        assert sorted(result) == ["alice", "bob", "charlie"]

    def test_mention_at_start(self):
        result = CollaborationService._parse_mentions("@john, this is urgent")
        assert result == ["john"]

    def test_mention_at_end(self):
        result = CollaborationService._parse_mentions("please review @john")
        assert result == ["john"]

    def test_mention_in_middle(self):
        result = CollaborationService._parse_mentions("check @bob and @alice")
        assert sorted(result) == ["alice", "bob"]

    def test_special_characters_around_mention(self):
        result = CollaborationService._parse_mentions("hey @john! @mary, thanks")
        assert sorted(result) == ["john", "mary"]

    def test_underscore_in_username(self):
        result = CollaborationService._parse_mentions("@john_doe please check")
        assert result == ["john_doe"]

    def test_numbers_in_username(self):
        result = CollaborationService._parse_mentions("ask @user123")
        assert result == ["user123"]

    def test_empty_string(self):
        result = CollaborationService._parse_mentions("")
        assert result == []

    def test_only_at_symbols(self):
        result = CollaborationService._parse_mentions("@@@")
        assert result == []

    def test_at_with_digits(self):
        result = CollaborationService._parse_mentions("@123 @!@")
        assert result == ["123"]


class TestCreateComment:
    """Test create_comment — comment creation with mention handling."""

    @pytest.fixture
    def mock_db(self):
        return Mock()

    def test_create_comment_basic(self, mock_db):
        mock_db.query.return_value.filter.return_value.first.return_value = None

        with patch.object(Comment, "to_dict", return_value={
            "id": 1, "use_case_id": 1, "user_name": "john",
            "content": "This is a comment",
            "created_at": "2024-01-01T00:00:00",
            "updated_at": "2024-01-01T00:00:00",
        }):
            result = CollaborationService.create_comment(
                mock_db, use_case_id=1, user_name="john",
                content="This is a comment"
            )

        assert result["user_name"] == "john"
        assert result["content"] == "This is a comment"
        assert result["use_case_id"] == 1
        mock_db.add.assert_called()
        mock_db.commit.assert_called()
        mock_db.refresh.assert_called()

    def test_create_comment_with_mention(self, mock_db):
        """Comment with @mention of an EXISTING user creates notification records."""
        # Mention-validation lookup (User by username) returns an existing user
        mock_db.query.return_value.filter.return_value.first.return_value = Mock(username="mary")

        with patch.object(Comment, "to_dict", return_value={
            "id": 1, "use_case_id": 1, "user_name": "john",
            "content": "Hey @mary review",
            "created_at": "2024-01-01T00:00:00",
            "updated_at": "2024-01-01T00:00:00",
        }):
            result = CollaborationService.create_comment(
                mock_db, use_case_id=1, user_name="john",
                content="Hey @mary review"
            )

        # db.add should be called 2 times: once for Comment, once for Notification
        assert mock_db.add.call_count == 2

    def test_create_comment_skips_nonexistent_mentions(self, mock_db):
        """A @mention that is not a real user creates no dead notification."""
        # Mention-validation lookup finds no such user
        mock_db.query.return_value.filter.return_value.first.return_value = None

        with patch.object(Comment, "to_dict", return_value={
            "id": 1, "use_case_id": 1, "user_name": "john",
            "content": "Hey @ghost review",
            "created_at": "2024-01-01T00:00:00",
            "updated_at": "2024-01-01T00:00:00",
        }):
            CollaborationService.create_comment(
                mock_db, use_case_id=1, user_name="john",
                content="Hey @ghost review"
            )

        # Only the Comment itself is added
        assert mock_db.add.call_count == 1

    def test_create_comment_no_mentions(self, mock_db):
        """Comment without @ mentions creates no notifications."""
        mock_db.query.return_value.filter.return_value.first.return_value = None

        with patch.object(Comment, "to_dict", return_value={
            "id": 1, "use_case_id": 1, "user_name": "john",
            "content": "Just a plain comment",
            "created_at": "2024-01-01T00:00:00",
            "updated_at": "2024-01-01T00:00:00",
        }):
            CollaborationService.create_comment(
                mock_db, use_case_id=1, user_name="john",
                content="Just a plain comment"
            )

        # Only Comment should be added, no Notification
        assert mock_db.add.call_count == 1

    def test_create_comment_sets_customer_id(self, mock_db):
        """Comment respects customer_id for notifications."""
        # Mention validation: @mary is an existing user
        mock_db.query.return_value.filter.return_value.first.return_value = Mock(username="mary")

        with patch.object(Comment, "to_dict", return_value={
            "id": 1, "use_case_id": 1, "user_name": "john",
            "content": "Note @mary",
            "created_at": "2024-01-01T00:00:00",
            "updated_at": "2024-01-01T00:00:00",
        }):
            CollaborationService.create_comment(
                mock_db, use_case_id=1, user_name="john",
                content="Note @mary", customer_id=1
            )

        assert mock_db.add.call_count == 2

    def test_create_comment_no_user_name(self, mock_db):
        """Comment with empty user_name is still created."""
        mock_db.query.return_value.filter.return_value.first.return_value = None

        with patch.object(Comment, "to_dict", return_value={
            "id": 1, "use_case_id": 1, "user_name": "",
            "content": "Test",
            "created_at": "2024-01-01T00:00:00",
            "updated_at": "2024-01-01T00:00:00",
        }):
            result = CollaborationService.create_comment(
                mock_db, use_case_id=1, user_name="", content="Test"
            )
        assert result is not None


class TestUpdateComment:
    """Test update_comment — update an existing comment."""

    @pytest.fixture
    def mock_db(self):
        return Mock()

    def test_update_comment_existing(self, mock_db):
        mock_comment = Mock()
        mock_comment.to_dict.return_value = {
            "id": 1, "content": "new content",
            "created_at": "2024-01-01T00:00:00",
            "updated_at": "2024-01-01T00:00:00",
        }
        mock_db.query.return_value.filter.return_value.first.return_value = mock_comment

        result = CollaborationService.update_comment(
            mock_db, comment_id=1, content="new content", user_name="john"
        )

        assert result is not None
        assert result["content"] == "new content"
        assert mock_comment.content == "new content"
        mock_db.commit.assert_called()
        mock_db.refresh.assert_called()

    def test_update_comment_not_found(self, mock_db):
        mock_db.query.return_value.filter.return_value.first.return_value = None

        result = CollaborationService.update_comment(
            mock_db, comment_id=999, content="new content", user_name="john"
        )
        assert result is None
        mock_db.commit.assert_not_called()


class TestDeleteComment:
    """Test delete_comment — delete an existing comment."""

    @pytest.fixture
    def mock_db(self):
        return Mock()

    def test_delete_comment_existing(self, mock_db):
        mock_comment = Mock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_comment

        result = CollaborationService.delete_comment(mock_db, comment_id=1)

        assert result is True
        mock_db.delete.assert_called_with(mock_comment)
        mock_db.commit.assert_called()

    def test_delete_comment_not_found(self, mock_db):
        mock_db.query.return_value.filter.return_value.first.return_value = None

        result = CollaborationService.delete_comment(mock_db, comment_id=999)
        assert result is False
        mock_db.delete.assert_not_called()


class TestGetComments:
    """Test get_comments — retrieve comments for a use case."""

    @pytest.fixture
    def mock_db(self):
        return Mock()

    def test_get_comments_returns_list(self, mock_db):
        c1 = Mock()
        c1.to_dict.return_value = {"id": 1, "use_case_id": 1, "user_name": "john", "content": "First"}
        c2 = Mock()
        c2.to_dict.return_value = {"id": 2, "use_case_id": 1, "user_name": "mary", "content": "Second"}
        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [c1, c2]

        result = CollaborationService.get_comments(mock_db, use_case_id=1)

        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["id"] == 1
        assert result[1]["id"] == 2

    def test_get_comments_empty(self, mock_db):
        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = []
        result = CollaborationService.get_comments(mock_db, use_case_id=99)
        assert result == []

    def test_get_comments_ordered(self, mock_db):
        c1 = Mock()
        c1.to_dict.return_value = {"id": 1}
        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [c1]

        CollaborationService.get_comments(mock_db, use_case_id=1)
        mock_db.query.return_value.filter.return_value.order_by.assert_called()


class TestGetUserNotifications:
    """Test get_user_notifications — retrieve notifications for a user."""

    @pytest.fixture
    def mock_db(self):
        return Mock()

    def test_get_notifications_for_user(self, mock_db):
        n1 = Mock()
        n1.to_dict.return_value = {"id": 1, "user_name": "john", "type": "mention", "read": False}
        n2 = Mock()
        n2.to_dict.return_value = {"id": 2, "user_name": "john", "type": "status_change", "read": True}
        mock_db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = [n1, n2]

        result = CollaborationService.get_user_notifications(mock_db, "john")

        assert isinstance(result, list)
        assert len(result) == 2

    def test_get_notifications_unread_only(self, mock_db):
        from unittest.mock import MagicMock

        q = MagicMock()
        q.filter.return_value = q
        q.order_by.return_value = q
        q.limit.return_value = q
        n1 = Mock()
        n1.to_dict.return_value = {"id": 1, "read": False}
        q.all.return_value = [n1]
        mock_db.query.return_value = q

        result = CollaborationService.get_user_notifications(
            mock_db, "john", unread_only=True
        )
        assert len(result) == 1
        assert result[0]["read"] is False

    def test_get_notifications_with_customer_filter(self, mock_db):
        from unittest.mock import MagicMock

        q = MagicMock()
        q.filter.return_value = q
        q.order_by.return_value = q
        q.limit.return_value = q
        n1 = Mock()
        n1.to_dict.return_value = {"id": 1, "user_name": "john"}
        q.all.return_value = [n1]
        mock_db.query.return_value = q

        CollaborationService.get_user_notifications(mock_db, "john", customer_id=1)
        assert q.filter.call_count >= 1

    def test_get_notifications_with_limit(self, mock_db):
        n1 = Mock()
        n1.to_dict.return_value = {"id": 1}
        mock_db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = [n1]

        CollaborationService.get_user_notifications(mock_db, "john", limit=1)
        mock_db.query.return_value.filter.return_value.order_by.return_value.limit.assert_called_with(1)

    def test_get_notifications_empty(self, mock_db):
        mock_db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []
        result = CollaborationService.get_user_notifications(mock_db, "nobody")
        assert result == []


class TestMarkAsRead:
    """Test mark_as_read — mark a notification as read."""

    @pytest.fixture
    def mock_db(self):
        return Mock()

    def test_mark_as_read_existing(self, mock_db):
        notification = Mock()
        notification.read = 0
        mock_db.query.return_value.filter.return_value.first.return_value = notification

        CollaborationService.mark_as_read(mock_db, notification_id=1)

        assert notification.read == 1
        mock_db.commit.assert_called()

    def test_mark_as_read_not_found(self, mock_db):
        mock_db.query.return_value.filter.return_value.first.return_value = None

        CollaborationService.mark_as_read(mock_db, notification_id=999)
        mock_db.commit.assert_not_called()


class TestBroadcastToCustomer:
    """Test broadcast_to_customer — create notifications for all customer users."""

    @pytest.fixture
    def mock_db(self):
        return Mock()

    @pytest.fixture
    def mock_customer_users(self):
        # recipients are ONE row per user with READ scope on the
        # customer (junction UNION central READ predicate). The fan-out query
        # also selects User.email — EL email delivery resolves the recipient
        # addresses from this SAME query (the settings are read once; the
        # query count never scales with the recipient count).
        return [("john", "john@example.test"), ("mary", "mary@example.test")]

    @pytest.fixture(autouse=True)
    def mock_email_service(self):
        # These unit pins cover the notification-creation contract on a
        # mocked session; the email wiring is proven on a real DB in
        # tests/backend/test_email_delivery.py. Stub the (disabled) email
        # settings so the mocked session is never queried for config.
        with patch("backend.services.collaboration_service.email_service") as stub:
            stub.effective_email_settings.return_value = {"enabled": False, "smtp_host": "", "from_address": ""}
            yield stub

    def test_broadcast_creates_notifications(self, mock_db, mock_customer_users):
        """Broadcasting creates a notification for each customer user."""
        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = mock_customer_users

        with patch.object(Notification, "to_dict", return_value={
            "id": 1, "user_name": "john", "type": "scoring",
            "message": "Use case scored: 85/100",
            "customer_id": 1, "read": False,
            "created_at": "2024-01-01T00:00:00",
        }):
            result = CollaborationService.broadcast_to_customer(
                mock_db, customer_id=1, event_type="scoring",
                message="Use case scored: 85/100"
            )

        assert len(result) == 2
        assert mock_db.add.call_count == 2

    def test_broadcast_empty_customer(self, mock_db):
        """Broadcasting to a customer with no users returns empty list."""
        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = []

        result = CollaborationService.broadcast_to_customer(
            mock_db, customer_id=99, event_type="status_change",
            message="Status changed"
        )

        assert result == []
        mock_db.add.assert_not_called()

    def test_broadcast_sets_customer_id(self, mock_db, mock_customer_users):
        """Broadcasting sets customer_id on each notification."""
        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = mock_customer_users

        with patch.object(Notification, "to_dict", return_value={
            "id": 1, "user_name": "john", "type": "scoring",
            "message": "Test", "customer_id": 1, "read": False,
            "created_at": "2024-01-01T00:00:00",
        }):
            CollaborationService.broadcast_to_customer(
                mock_db, customer_id=5, event_type="scoring",
                message="Test"
            )

        assert mock_db.add.call_count == 2

    def test_broadcast_event_type_propagated(self, mock_db, mock_customer_users):
        """Event type is correctly set on all notifications."""
        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = mock_customer_users

        with patch.object(Notification, "to_dict", return_value={
            "id": 1, "user_name": "john", "type": "status_change",
            "message": "Status changed", "customer_id": 1, "read": False,
            "created_at": "2024-01-01T00:00:00",
        }):
            CollaborationService.broadcast_to_customer(
                mock_db, customer_id=1, event_type="status_change",
                message="Status changed"
            )

        assert mock_db.add.call_count == 2

    def test_broadcast_excludes_actor(self, mock_db, mock_customer_users):
        """exclude_user skips the actor so they are not notified of their own action."""
        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = mock_customer_users

        with patch.object(Notification, "to_dict", return_value={
            "id": 1, "user_name": "mary", "type": "comment_added",
            "message": "john commented", "customer_id": 1, "read": False,
            "created_at": "2024-01-01T00:00:00",
        }):
            result = CollaborationService.broadcast_to_customer(
                mock_db, customer_id=1, event_type="comment_added",
                message="john commented", exclude_user="john"
            )

        assert len(result) == 1
        assert mock_db.add.call_count == 1


class TestCommentOwnership:
    """get_comment / get_notification / can_modify_comment helpers."""

    @pytest.fixture
    def mock_db(self):
        return Mock()

    def test_get_comment_found(self, mock_db):
        c = Mock()
        mock_db.query.return_value.filter.return_value.first.return_value = c
        assert CollaborationService.get_comment(mock_db, 1) is c

    def test_get_comment_missing(self, mock_db):
        mock_db.query.return_value.filter.return_value.first.return_value = None
        assert CollaborationService.get_comment(mock_db, 999) is None

    def test_get_notification_found(self, mock_db):
        n = Mock()
        mock_db.query.return_value.filter.return_value.first.return_value = n
        assert CollaborationService.get_notification(mock_db, 1) is n

    def test_get_notification_missing(self, mock_db):
        mock_db.query.return_value.filter.return_value.first.return_value = None
        assert CollaborationService.get_notification(mock_db, 999) is None

    def test_can_modify_own_comment(self):
        c = Mock()
        c.user_name = "john"
        assert CollaborationService.can_modify_comment(
            c, {"username": "john", "is_admin": 0}
        ) is True

    def test_cannot_modify_foreign_comment(self):
        c = Mock()
        c.user_name = "john"
        assert CollaborationService.can_modify_comment(
            c, {"username": "mary", "is_admin": 0}
        ) is False

    def test_admin_can_modify_any_comment(self):
        c = Mock()
        c.user_name = "john"
        assert CollaborationService.can_modify_comment(
            c, {"username": "mary", "is_admin": 1}
        ) is True
