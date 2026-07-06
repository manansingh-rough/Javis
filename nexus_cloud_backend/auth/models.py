"""
nexus_cloud_backend/auth/models.py

Pydantic models for auth request/response schemas.
"""

from datetime import datetime
from typing import Optional, List

from pydantic import BaseModel, EmailStr


class SignupRequest(BaseModel):
    email: EmailStr
    password: Optional[str] = None
    oauth_provider: Optional[str] = None
    oauth_token: Optional[str] = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    email: str


class UserProfileResponse(BaseModel):
    id: str
    email: str
    tier: str = "free"
    org_id: Optional[str] = None
    telemetry_consent: bool = False
    created_at: datetime