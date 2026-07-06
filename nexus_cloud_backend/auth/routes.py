"""
nexus_cloud_backend/auth/routes.py

Authentication endpoints: signup, login, OAuth2 callback, profile.
Stub implementation — production deployments should use a proper auth
library (FastAPI Users, Authlib) with password hashing and JWT.
"""

import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional

import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from nexus_cloud_backend.core.config import get_settings
from nexus_cloud_backend.auth.models import SignupRequest, LoginRequest, AuthResponse, UserProfileResponse

router = APIRouter(prefix="/auth", tags=["auth"])


def _create_jwt(user_id: str, email: str) -> str:
    """Create a JWT access token."""
    settings = get_settings()
    payload = {
        "sub": user_id,
        "email": email,
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(hours=settings.JWT_EXPIRY_HOURS),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


@router.post("/signup", response_model=AuthResponse)
async def signup(request: SignupRequest):
    """Create a new user account.

    In production, this would:
      1. Validate email uniqueness
      2. Hash the password with bcrypt/argon2
      3. Create the user in the database
      4. Optionally create a Stripe/Paddle customer
    """
    # Stub: generate a user ID and JWT
    user_id = str(uuid.uuid4())
    token = _create_jwt(user_id, request.email)

    return AuthResponse(
        access_token=token,
        user_id=user_id,
        email=request.email,
    )


@router.post("/login", response_model=AuthResponse)
async def login(request: LoginRequest):
    """Authenticate a user with email and password.

    In production, this would:
      1. Look up the user by email
      2. Verify the password hash
      3. Return a JWT
    """
    # Stub: accept any login in dev mode
    user_id = str(uuid.uuid4())
    token = _create_jwt(user_id, request.email)

    return AuthResponse(
        access_token=token,
        user_id=user_id,
        email=request.email,
    )


@router.get("/me", response_model=UserProfileResponse)
async def get_profile():
    """Get the current user's profile.

    Requires authentication. In production, extract user from JWT.
    """
    # Stub response
    return UserProfileResponse(
        id=str(uuid.uuid4()),
        email="user@example.com",
        tier="free",
        created_at=datetime.now(timezone.utc),
    )


@router.post("/oauth/google")
async def oauth_google(code: str):
    """Handle Google OAuth2 callback.

    In production, exchange the authorization code for tokens via
    google.oauth2 library and create/lookup the user.
    """
    # Stub
    user_id = str(uuid.uuid4())
    token = _create_jwt(user_id, "google-user@example.com")

    return AuthResponse(
        access_token=token,
        user_id=user_id,
        email="google-user@example.com",
    )