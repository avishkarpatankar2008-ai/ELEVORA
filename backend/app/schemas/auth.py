from typing import Literal, Optional

import unicodedata

from pydantic import BaseModel, EmailStr, Field, StrictBool, field_validator

from app.core.text import clean_language_name


def _reject_control_characters(value: str) -> str:
    if any(unicodedata.category(ch)[0] == "C" for ch in value):
        raise ValueError("Control characters are not allowed.")
    return value


class RegisterRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)

    @field_validator("name")
    @classmethod
    def strip_name(cls, v: str) -> str:
        v = _reject_control_characters(v.strip())
        if not v:
            raise ValueError("Name cannot be blank")
        return v


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class UserPreferencesUpdate(BaseModel):
    language: Optional[str] = Field(default=None, min_length=2, max_length=40)

    @field_validator("language")
    @classmethod
    def clean_language(cls, v: Optional[str]) -> Optional[str]:
        """The saved language is later interpolated into model prompts, so it must
        be a plain language name, not free text."""
        if v is None:
            return None
        cleaned = clean_language_name(v)
        if len(cleaned) < 2 or cleaned != v.strip():
            raise ValueError("Language must be a plain language name such as 'English' or 'Hindi'.")
        return cleaned

    defaultDifficulty: Optional[Literal["easy", "medium", "hard"]] = None
    # Strict: "yes" / "1" must not silently become True over the wire.
    autoPlayQuestion: Optional[StrictBool] = None
    cameraEnabledByDefault: Optional[StrictBool] = None


class UserUpdateRequest(BaseModel):
    """Payload for PATCH /auth/me. Everything optional — only what's supplied
    is changed. Email and password are deliberately out of scope here (they
    need their own verification flows, not a quiet settings-page update)."""

    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    preferences: Optional[UserPreferencesUpdate] = None

    @field_validator("name")
    @classmethod
    def strip_name(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        v = _reject_control_characters(v.strip())
        if not v:
            raise ValueError("Name cannot be blank")
        return v
