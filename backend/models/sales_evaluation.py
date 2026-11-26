"""Sales evaluation SQLAlchemy model."""

import sqlalchemy as sa

from backend.models.use_case import Base


class SalesEvaluation(Base):
    __tablename__ = "sales_evaluations"

    id = sa.Column(sa.Integer, primary_key=True, nullable=False, index=True)
    customer_id = sa.Column(sa.Integer, sa.ForeignKey("customers.id", ondelete="CASCADE"), nullable=False)
    evaluation_name = sa.Column(sa.String(255), nullable=False)
    readiness_overall = sa.Column(sa.Float, nullable=True)
    readiness_dimensions = sa.Column(sa.JSON, nullable=True)
    environment_score = sa.Column(sa.Float, nullable=True)
    environment_factors = sa.Column(sa.JSON, nullable=True)
    growth_opportunities = sa.Column(sa.JSON, nullable=True)
    risk_factors = sa.Column(sa.JSON, nullable=True)
    sales_approach = sa.Column(sa.JSON, nullable=True)
    # S-A-I-L P5 — persona-driven evaluations (CHANGELOG 0.0.80 items 27-39):
    # the audience context (persona) under which the evaluation was generated,
    # the source-context metadata (provenance: which sources + indicators the
    # engine consumed), and the persona-tailored section set. All nullable so
    # pre-P5 rows stay valid (persona NULL = generic / legacy).
    persona = sa.Column(sa.String(50), nullable=True, index=True)
    source_context = sa.Column(sa.JSON, nullable=True)
    persona_sections = sa.Column(sa.JSON, nullable=True)
    status = sa.Column(sa.String(20), nullable=False, default="draft")
    created_at = sa.Column(sa.DateTime, nullable=False, server_default=sa.func.current_timestamp())
    updated_at = sa.Column(sa.DateTime, nullable=False, server_default=sa.func.current_timestamp(), onupdate=sa.func.current_timestamp())
