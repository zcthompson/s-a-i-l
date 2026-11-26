"""Unit tests for CustomerUserService (junction table CRUD operations)."""

import os

os.environ.setdefault("SAIL_JWT_SECRET", "test-secret-for-unit-tests-only-00000000")

from unittest.mock import Mock

import pytest
from backend.services.customer_user_service import (
    CustomerUserService,
    has_admin_access,
    has_write_access,
    is_readonly,
)


class TestRoleHelpers:
    """Test junction role helper functions."""

    def test_is_readonly_auditor(self):
        """Auditor role should be read-only."""
        assert is_readonly("auditor") is True

    def test_is_readonly_owner(self):
        """Owner role should NOT be read-only."""
        assert is_readonly("owner") is False

    def test_is_readonly_member(self):
        """Member role should NOT be read-only."""
        assert is_readonly("member") is False

    def test_has_write_access_owner(self):
        """Owner should have write access."""
        assert has_write_access("owner") is True

    def test_has_write_access_member(self):
        """Member should have write access."""
        assert has_write_access("member") is True

    def test_has_write_access_auditor(self):
        """Auditor should NOT have write access."""
        assert has_write_access("auditor") is False

    def test_has_admin_access_owner(self):
        """Owner should have admin access."""
        assert has_admin_access("owner") is True

    def test_has_admin_access_member(self):
        """Member should NOT have admin access."""
        assert has_admin_access("member") is False

    def test_has_admin_access_auditor(self):
        """Auditor should NOT have admin access."""
        assert has_admin_access("auditor") is False


class TestCustomerUserService:
    """Test junction table CRUD operations."""

    @pytest.fixture
    def mock_db(self):
        """Create a mock database session."""
        return Mock()

    @pytest.fixture
    def mock_customer(self):
        """Create a mock customer."""
        customer = Mock()
        customer.id = 1
        customer.name = "Test Customer"
        return customer

    @pytest.fixture
    def mock_user(self):
        """Create a mock user."""
        user = Mock()
        user.id = 1
        user.username = "testuser"
        user.is_admin = 0
        return user

    @pytest.fixture
    def mock_admin_user(self):
        """Create a mock admin user."""
        admin = Mock()
        admin.id = 99
        admin.username = "admin"
        admin.is_admin = 1
        return admin

    def test_is_readonly_auditor(self):
        """Auditor role is read-only."""
        assert is_readonly("auditor") is True
        assert is_readonly("owner") is False
        assert is_readonly("member") is False

    def test_has_write_access(self):
        """Owner and member have write access."""
        assert has_write_access("owner") is True
        assert has_write_access("member") is True
        assert has_write_access("auditor") is False

    def test_has_admin_access(self):
        """Only owner has admin access."""
        assert has_admin_access("owner") is True
        assert has_admin_access("member") is False
        assert has_admin_access("auditor") is False

    def test_add_user_to_customer_invalid_role(self, mock_db):
        """Adding user with invalid role should raise ValueError."""
        customer = Mock()
        customer.id = 1
        user = Mock()
        user.id = 1

        with pytest.raises(ValueError, match="Invalid junction role"):
            CustomerUserService.add_user_to_customer(
                mock_db, customer, user, user, role="invalid"
            )

    def test_add_user_to_customer_duplicate(self, mock_db):
        """Adding user that already exists should raise ValueError."""
        mock_record = Mock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_record

        customer = Mock()
        customer.id = 1
        user = Mock()
        user.id = 1
        admin_user = Mock()
        admin_user.id = 2

        with pytest.raises(ValueError, match="already assigned"):
            CustomerUserService.add_user_to_customer(
                mock_db, customer, user, admin_user, role="member"
            )

    def test_get_user_customer_ids_admin(self, mock_db):
        """Admin users should get empty list (see all)."""
        admin_user = {"is_admin": 1, "user_id": 1}
        result = CustomerUserService.get_user_customer_ids(mock_db, admin_user)
        assert result == []

    def test_get_user_customer_ids_no_user_id(self, mock_db):
        """Users without user_id should get empty list."""
        user = {"is_admin": 0}  # No user_id
        result = CustomerUserService.get_user_customer_ids(mock_db, user)
        assert result == []

    def test_get_user_customer_ids_no_legacy(self, mock_db):
        """Users with no junction or legacy data should get empty list."""
        mock_db.query.return_value.filter.return_value.all.return_value = []

        user = {"is_admin": 0, "user_id": 1, "customer_id": None}
        result = CustomerUserService.get_user_customer_ids(mock_db, user)
        assert result == []

    def test_get_user_customer_ids_junction_preferred(self, mock_db):
        """Junction table data is preferred over legacy customer_id."""
        # Junction returns 2 customer IDs
        mock_db.query.return_value.filter.return_value.all.return_value = [
            (10,),
            (20,),
        ]

        user = {"is_admin": 0, "user_id": 1, "customer_id": 99}  # legacy is 99
        result = CustomerUserService.get_user_customer_ids(mock_db, user)
        assert result == [10, 20]
        # Legacy customer_id should be ignored when junction data exists
        assert 99 not in result

    def test_has_access_true(self, mock_db):
        """User has access if junction record exists."""
        mock_record = Mock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_record

        user = Mock()
        user.id = 1

        result = CustomerUserService.has_access(mock_db, user, 1)
        assert result is True

    def test_has_access_false(self, mock_db):
        """User has no access if no junction record exists."""
        mock_db.query.return_value.filter.return_value.first.return_value = None

        user = Mock()
        user.id = 1

        result = CustomerUserService.has_access(mock_db, user, 1)
        assert result is False

    def test_get_permission_level_owner(self, mock_db):
        """Get junction role for user."""
        mock_record = Mock()
        mock_record.role = "owner"
        mock_db.query.return_value.filter.return_value.first.return_value = mock_record

        user = Mock()
        user.id = 1

        result = CustomerUserService.get_permission_level(mock_db, user, 1)
        assert result == "owner"

    def test_get_permission_level_no_access(self, mock_db):
        """Return 'none' when user has no access."""
        mock_db.query.return_value.filter.return_value.first.return_value = None

        user = Mock()
        user.id = 1

        result = CustomerUserService.get_permission_level(mock_db, user, 1)
        assert result == "none"

    def test_is_owner_or_admin_global(self, mock_db):
        """Global admin always has access."""
        user = Mock()
        user.is_admin = 1

        result = CustomerUserService.is_owner_or_admin(mock_db, user, Mock())
        assert result is True

    def test_is_owner_or_admin_junction_owner(self, mock_db):
        """Junction owner has access."""
        mock_record = Mock()
        mock_record.role = "owner"
        mock_db.query.return_value.filter.return_value.first.return_value = mock_record

        user = Mock()
        user.is_admin = 0

        result = CustomerUserService.is_owner_or_admin(mock_db, user, Mock())
        assert result is True

    def test_is_owner_or_admin_not_owner(self, mock_db):
        """Non-admin without junction access has no access."""
        mock_db.query.return_value.filter.return_value.first.return_value = None

        user = Mock()
        user.is_admin = 0

        result = CustomerUserService.is_owner_or_admin(mock_db, user, Mock())
        assert result is False

    def test_is_admin_for_customer_admin(self, mock_db):
        """Global admin is admin for all customers."""
        user = Mock()
        user.is_admin = 1

        result = CustomerUserService.is_admin_for_customer(mock_db, user, Mock())
        assert result is True

    def test_is_admin_for_customer_owner(self, mock_db):
        """Junction owner is admin for their customer."""
        mock_record = Mock()
        mock_record.role = "owner"
        mock_db.query.return_value.filter.return_value.first.return_value = mock_record

        user = Mock()
        user.is_admin = 0

        result = CustomerUserService.is_admin_for_customer(mock_db, user, Mock())
        assert result is True

    def test_is_admin_for_customer_member(self, mock_db):
        """Member is not admin for their customer."""
        mock_record = Mock()
        mock_record.role = "member"
        mock_db.query.return_value.filter.return_value.first.return_value = mock_record

        user = Mock()
        user.is_admin = 0

        result = CustomerUserService.is_admin_for_customer(mock_db, user, Mock())
        assert result is False

    def test_update_role_invalid_role(self, mock_db):
        """Updating to invalid role should raise ValueError."""
        customer = Mock()
        customer.id = 1
        user = Mock()
        user.id = 1

        with pytest.raises(ValueError, match="Invalid junction role"):
            CustomerUserService.update_role(mock_db, customer, user, "invalid")

    def test_update_role_not_assigned(self, mock_db):
        """Updating role for non-assigned user should raise ValueError."""
        mock_db.query.return_value.filter.return_value.first.return_value = None

        customer = Mock()
        customer.id = 1
        user = Mock()
        user.id = 1

        with pytest.raises(ValueError, match="not assigned"):
            CustomerUserService.update_role(mock_db, customer, user, "owner")
