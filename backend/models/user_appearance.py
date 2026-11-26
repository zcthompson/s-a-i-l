"""Account-scoped appearance; layout density remains device-local."""
import sqlalchemy as sa

from backend.models.use_case import Base


class UserAppearance(Base):
    __tablename__ = "user_appearance"
    user_id = sa.Column(sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    theme = sa.Column(sa.String(5), nullable=False)
    font_size = sa.Column(sa.String(6), nullable=False)
