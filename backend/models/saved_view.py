"""Personal filter descriptions; loading a view never grants account access."""

import sqlalchemy as sa

from backend.models.use_case import Base


class SavedView(Base):
    __tablename__ = "saved_views"
    __table_args__ = (sa.UniqueConstraint("user_id", "surface", "name_norm", name="uq_saved_view_owner_surface_name"),)

    id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)
    user_id = sa.Column(sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name = sa.Column(sa.Text, nullable=False)
    name_norm = sa.Column(sa.Text, nullable=False)
    surface = sa.Column(sa.Text, nullable=False)
    params = sa.Column(sa.JSON, nullable=False)
    schema_version = sa.Column(sa.Integer, nullable=False, server_default="1")
    created_at = sa.Column(sa.DateTime, nullable=False, server_default=sa.func.current_timestamp())
    updated_at = sa.Column(sa.DateTime, nullable=False, server_default=sa.func.current_timestamp(),
                           onupdate=sa.func.current_timestamp())
