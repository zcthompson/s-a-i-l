"""Customer-owned contact observations and explicit buying roles."""

import sqlalchemy as sa
from sqlalchemy.orm import relationship

from backend.models.sales_note import _iso
from backend.models.use_case import Base
from backend.services.sales_personas import get_persona

BUYING_ROLES = ("economic_buyer", "decision_maker", "champion", "technical_buyer",
                "influencer", "end_user")
BUYING_ROLE_LABELS = dict(zip(BUYING_ROLES, ("Economic buyer", "Decision maker", "Champion",
                                           "Technical buyer", "Influencer", "End user")))


def _junction(name, key, target):
    return sa.Table(
        name, Base.metadata,
        sa.Column("contact_id", sa.Integer, sa.ForeignKey("customer_contacts.id", ondelete="CASCADE"),
                  primary_key=True, nullable=False, index=True),
        sa.Column(key, sa.Integer, sa.ForeignKey(target, ondelete="CASCADE"),
                  primary_key=True, nullable=False),
    )


contact_notes = _junction("contact_notes", "note_id", "sales_notes.id")
contact_use_cases = _junction("contact_use_cases", "use_case_id", "use_cases.id")
contact_technologies = _junction("contact_technologies", "technology_id", "customer_technologies.id")


class CustomerContact(Base):
    __tablename__ = "customer_contacts"
    # IDs are never reissued (ER-12): retained references must not attach to a new row.
    __table_args__ = {"sqlite_autoincrement": True}

    id = sa.Column(sa.Integer, primary_key=True)
    customer_id = sa.Column(sa.Integer, sa.ForeignKey("customers.id", ondelete="CASCADE"),
                            nullable=False, index=True)
    display_name = sa.Column(sa.String(255), nullable=False)
    title = sa.Column(sa.String(255))
    email = sa.Column(sa.String(255))
    phone = sa.Column(sa.String(50))
    department = sa.Column(sa.String(100))
    persona = sa.Column(sa.String(50))
    source = sa.Column(sa.String(255))
    observation_date = sa.Column(sa.Date)
    verification_state = sa.Column(sa.String(20), nullable=False, default="verified")
    archived = sa.Column(sa.Boolean, nullable=False, server_default=sa.false())
    archived_at = sa.Column(sa.DateTime)
    created_by = sa.Column(sa.String(255))
    updated_by = sa.Column(sa.String(255))
    created_at = sa.Column(sa.DateTime, nullable=False, server_default=sa.func.current_timestamp())
    updated_at = sa.Column(sa.DateTime, nullable=False, server_default=sa.func.current_timestamp(),
                           onupdate=sa.func.current_timestamp())
    related_notes = relationship("SalesNote", secondary=contact_notes, lazy="select", backref="related_contacts")
    related_use_cases = relationship("UseCase", secondary=contact_use_cases, lazy="select")
    related_technologies = relationship("CustomerTechnology", secondary=contact_technologies, lazy="select")
    buying_roles = relationship("ContactBuyingRole", cascade="all, delete-orphan", lazy="select")

    def to_dict(self):
        result = {column.name: getattr(self, column.name) for column in self.__table__.columns}
        for key in ("observation_date", "archived_at", "created_at", "updated_at"):
            result[key] = _iso(result[key])
        persona = get_persona(self.persona)
        result["persona_label"] = persona["label"] if persona else None
        result["buying_roles"] = [role.to_dict() for role in self.buying_roles]
        for name in ("note", "use_case", "technology"):
            cache = f"_related_{name}_ids"
            relation = {"note": "related_notes", "use_case": "related_use_cases",
                        "technology": "related_technologies"}[name]
            result[f"related_{name}_ids"] = (getattr(self, cache) if hasattr(self, cache)
                                              else [row.id for row in getattr(self, relation)])
        result["note_count"] = len(result["related_note_ids"])
        return result


class ContactBuyingRole(Base):
    __tablename__ = "contact_buying_roles"
    __table_args__ = (sa.UniqueConstraint("contact_id", "role", name="uq_contact_buying_role"),)

    id = sa.Column(sa.Integer, primary_key=True)
    contact_id = sa.Column(sa.Integer, sa.ForeignKey("customer_contacts.id", ondelete="CASCADE"),
                           nullable=False, index=True)
    role = sa.Column(sa.String(50), nullable=False)
    source = sa.Column(sa.String(255))
    observation_date = sa.Column(sa.Date)
    verification_state = sa.Column(sa.String(20), nullable=False, default="verified")
    created_at = sa.Column(sa.DateTime, server_default=sa.func.current_timestamp())

    def to_dict(self):
        return {"role": self.role, "role_label": BUYING_ROLE_LABELS[self.role],
                "source": self.source, "observation_date": _iso(self.observation_date),
                "verification_state": self.verification_state}
