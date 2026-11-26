"""Service-level tests for use-case technology tracking fields.

Covers: tech_stack, devices, software, vendor on UseCase model,
UseCaseService.create/update, and Customer.tech_profile to_dict inclusion.
"""

from backend.services.use_case_service import UseCaseService


class TestUseCaseTechTracking:
    """Technology tracking fields on UseCase."""

    def test_create_with_tech_fields(self, db_session):
        """Create a UseCase with tech_stack, devices, software, vendor and assert persisted."""
        from backend.models.use_case import Customer
        db_session.add(Customer(id=1, name="Technology tracking customer"))
        db_session.commit()
        uc = UseCaseService.create(
            db=db_session,
            title="Tech Test Use Case",
            description="Testing tech tracking",
            customer_id=1,
            tech_stack={"cloud": "aws", "lang": "python"},
            devices={"laptops": 10, "servers": 3},
            software={"db": "postgres", "cache": "redis"},
            vendor="Acme Corp",
        )
        assert uc.tech_stack == {"cloud": "aws", "lang": "python"}
        assert uc.devices == {"laptops": 10, "servers": 3}
        assert uc.software == {"db": "postgres", "cache": "redis"}
        assert uc.vendor == "Acme Corp"

        # Verify to_dict includes tech fields
        d = uc.to_dict()
        assert d["tech_stack"] == {"cloud": "aws", "lang": "python"}
        assert d["devices"] == {"laptops": 10, "servers": 3}
        assert d["software"] == {"db": "postgres", "cache": "redis"}
        assert d["vendor"] == "Acme Corp"

    def test_update_changes_vendor_and_tech_stack(self, db_session):
        """Update a UseCase and verify vendor and tech_stack are updated via setattr."""
        from backend.models.use_case import Customer
        db_session.add(Customer(id=1, name="Technology tracking customer"))
        db_session.commit()
        uc = UseCaseService.create(
            db=db_session,
            title="Updatable Use Case",
            customer_id=1,
            vendor="Old Vendor",
            tech_stack={"old": "tech"},
        )
        updated = UseCaseService.update(
            db=db_session,
            use_case_id=uc.id,
            user={"username": "admin", "is_admin": 1},
            vendor="New Vendor",
            tech_stack={"new": "tech"},
        )
        assert updated.vendor == "New Vendor"
        assert updated.tech_stack == {"new": "tech"}

        # Verify to_dict reflects changes
        d = updated.to_dict()
        assert d["vendor"] == "New Vendor"
        assert d["tech_stack"] == {"new": "tech"}

    def test_customer_tech_profile_to_dict(self, db_session):
        """Customer.tech_profile set/get and to_dict inclusion."""
        # Seed a customer with tech_profile
        from backend.models.use_case import Customer as CustomerModel

        cust = CustomerModel(
            name="TechCustomer",
            tech_profile={"industry": "FinTech", "primary_stack": "AWS"},
        )
        db_session.add(cust)
        db_session.commit()

        # Verify to_dict includes tech_profile
        d = cust.to_dict()
        assert d["tech_profile"] == {"industry": "FinTech", "primary_stack": "AWS"}

    def test_create_without_tech_fields_defaults_to_none(self, db_session):
        """Create UseCase without tech fields; they should be None / absent in to_dict."""
        from backend.models.use_case import Customer
        db_session.add(Customer(id=1, name="Technology tracking customer"))
        db_session.commit()
        uc = UseCaseService.create(
            db=db_session,
            title="Bare Use Case",
            customer_id=1,
        )
        assert uc.tech_stack is None
        assert uc.devices is None
        assert uc.software is None
        assert uc.vendor is None

        d = uc.to_dict()
        # to_dict should not include keys with None values (or should include them as None)
        # Check that the keys exist but are None
        assert "tech_stack" in d
        assert d["tech_stack"] is None
        assert "devices" in d
        assert d["devices"] is None
        assert "software" in d
        assert d["software"] is None
        assert "vendor" in d
        assert d["vendor"] is None
