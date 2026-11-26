"""Comment, collaboration, and audit trail models."""

from datetime import datetime

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)

from backend.models.use_case import Base


class Comment(Base):
    """A comment on a use case."""
    __tablename__ = "comments"

    id = Column(Integer, primary_key=True, nullable=False, index=True)
    use_case_id = Column(Integer, ForeignKey("use_cases.id"), nullable=False, index=True)
    user_name = Column(String(100), nullable=False, default="Anonymous")
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def to_dict(self):
        return {
            "id": self.id,
            "use_case_id": self.use_case_id,
            "user_name": self.user_name,
            "content": self.content,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


class Notification(Base):
    """Notification record for users."""
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, nullable=False, index=True)
    user_name = Column(String(100), nullable=False)
    type = Column(String(50), nullable=False)  # comment, scoring, mention
    message = Column(Text, nullable=False)
    customer_id = Column(Integer, nullable=True, index=True)
    read = Column(Integer, default=0, nullable=False)  # 0 = unread
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    def to_dict(self):
        # Handle both runtime values (datetime or None) and column descriptors
        ca = self.__dict__.get("created_at")
        if ca is not None and not isinstance(ca, type):
            return {
                "id": self.id,
                "user_name": self.user_name,
                "type": self.type,
                "message": self.message,
                "customer_id": self.customer_id,
                "read": bool(self.read),
                "created_at": ca.isoformat(),
            }
        return {
            "id": self.id,
            "user_name": self.user_name,
            "type": self.type,
            "message": self.message,
            "customer_id": self.customer_id,
            "read": bool(self.read),
            "created_at": None,
        }


class ScoreHistory(Base):
    """Structured audit trail for score changes."""
    __tablename__ = "score_history"

    id = Column(Integer, primary_key=True, nullable=False, index=True)
    use_case_id = Column(Integer, ForeignKey("use_cases.id"), nullable=False)
    score = Column(Float, nullable=False)
    scored_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    scored_by = Column(String(100), nullable=False, default="anonymous")
    is_manual = Column(Integer, default=0)
    reasoning = Column(Text, nullable=True)
    status = Column(String(20), default="draft")  # draft | approved | rejected
    dimension_scores = Column(JSON, nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "use_case_id": self.use_case_id,
            "score": self.score,
            "scored_at": self.scored_at.isoformat() if self.scored_at else None,
            "scored_by": self.scored_by,
            "is_manual": bool(self.is_manual),
            "reasoning": self.reasoning,
            "status": self.status,
            "dimension_scores": self.dimension_scores,
        }


class DimensionConfig(Base):
    """Versioned scoring dimension definitions."""
    __tablename__ = "dimension_configs"

    id = Column(Integer, primary_key=True, nullable=False, index=True)
    version = Column(String(20), nullable=False, default="1")
    name = Column(String(100), nullable=False)
    weight = Column(Float, nullable=False)
    is_active = Column(Integer, default=1)
    created_at = Column(DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "version": self.version,
            "name": self.name,
            "weight": self.weight,
            "is_active": bool(self.is_active),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class AuditLog(Base):
    """Persistent audit trail for security-sensitive operations.

    Covers customer sharing (add/remove/change role), scoring, status changes,
    and any other operation that affects data access boundaries.
    """
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_customer_id", "customer_id"),
        Index("ix_audit_logs_action", "action"),
    )

    id = Column(Integer, primary_key=True, nullable=False, index=True)
    user_id = Column(Integer, nullable=False)  # ID of the actor
    username = Column(String(100), nullable=False, default="anonymous")
    action = Column(String(50), nullable=False)  # add_user, remove_user, update_role, score, status_change
    customer_id = Column(Integer, nullable=True)  # index handled by __table_args__
    target_id = Column(Integer, nullable=True)  # ID of the affected resource (user_id, use_case_id, etc.)
    details = Column(Text, nullable=True)  # JSON string or description
    ip_address = Column(String(45), nullable=True)  # IPv4 or IPv6
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "username": self.username,
            "action": self.action,
            "customer_id": self.customer_id,
            "target_id": self.target_id,
            "details": self.details,
            "ip_address": self.ip_address,
            "created_at": self.created_at.isoformat(),
        }


class SystemConfig(Base):
    """Persistent application configuration stored in the database.

    Covers inference settings, assessment evaluation, project settings,
    and integration configuration. Admin-only CRUD.
    """
    __tablename__ = "system_config"

    id = Column(Integer, primary_key=True, nullable=False, index=True)
    category = Column(String(50), nullable=False, index=True)  # inference, assessment, project, integration
    key = Column(String(100), nullable=False, index=True)  # unique per category
    value_type = Column(String(20), default="string", nullable=False)  # string, integer, float, boolean, json
    string_value = Column(Text, nullable=True)
    integer_value = Column(Integer, nullable=True)
    float_value = Column(Float, nullable=True)
    boolean_value = Column(Integer, default=0, nullable=True)  # 0/1
    json_value = Column(JSON, nullable=True)
    description = Column(Text, nullable=True)
    is_active = Column(Integer, default=1, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def to_dict(self):
        value = None
        if self.value_type == "string":
            value = self.string_value
        elif self.value_type == "integer":
            value = self.integer_value
        elif self.value_type == "float":
            value = self.float_value
        elif self.value_type == "boolean":
            value = bool(self.boolean_value)
        elif self.value_type == "json":
            value = self.json_value
        return {
            "id": self.id,
            "category": self.category,
            "key": self.key,
            "value_type": self.value_type,
            "value": value,
            "description": self.description,
            "is_active": bool(self.is_active),
            "created_at": self.created_at.isoformat() if self.created_at is not None else None,  # type: ignore[union-attr]
            "updated_at": self.updated_at.isoformat() if self.updated_at is not None else None,  # type: ignore[union-attr]
        }
