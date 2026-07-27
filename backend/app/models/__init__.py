"""Model registry.

Import every model here. Alembic's autogenerate walks `Base.metadata`, and a
model that is never imported is invisible to it.
"""

from app.db.base import Base
from app.models.refresh_token import RefreshToken
from app.models.user import User, UserRole

__all__ = ["Base", "RefreshToken", "User", "UserRole"]
