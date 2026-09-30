"""S4: create_access_token must work with and without an explicit expiry."""

import jwt

from app.config import settings
from app.middleware.auth import create_access_token


def _claims(token: str) -> dict:
    return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])


def test_default_expiry_from_settings():
    claims = _claims(create_access_token("agent@demo.local"))
    assert claims["sub"] == "agent@demo.local"
    assert claims["exp"] - claims["iat"] == settings.jwt_expiration_minutes * 60


def test_explicit_expiry_seconds():
    # Before the fix, passing expires_delta_seconds raised UnboundLocalError ('expire')
    claims = _claims(create_access_token("admin@demo.local", expires_delta_seconds=120,
                                         is_admin=True))
    assert claims["exp"] - claims["iat"] == 120
    assert claims["is_admin"] is True
