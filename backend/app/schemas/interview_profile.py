from datetime import datetime
from typing import Literal, Optional

import unicodedata

from pydantic import BaseModel, Field, field_validator, model_validator

ProfileDifficulty = Literal["easy", "medium", "hard", "adaptive"]

MAX_LIST_ITEM_CHARS = 120


def _clean_text(value: str) -> str:
    """Trim, drop control/invisible characters, and collapse inner whitespace."""
    kept = "".join(
        ch if ch.isspace() else ch
        for ch in unicodedata.normalize("NFC", value)
        if ch.isspace() or unicodedata.category(ch)[0] != "C"
    )
    return " ".join(kept.split())


def _clean_items(items: list[str]) -> list[str]:
    """Clean each entry, drop blanks and case-insensitive duplicates, and enforce a
    per-item length so one entry can't carry a whole prompt."""
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = _clean_text(item)
        if not text:
            continue
        if len(text) > MAX_LIST_ITEM_CHARS:
            raise ValueError(f"Each entry must be at most {MAX_LIST_ITEM_CHARS} characters.")
        key = text.casefold()
        if key not in seen:
            seen.add(key)
            cleaned.append(text)
    return cleaned


class InterviewProfileBase(BaseModel):
    """Shared shape for creating/reading a reusable Interview Profile.

    This is the Phase 8 upgrade the Phase 2 InterviewProfile schema
    (app/schemas/profile.py) already anticipated: a named, stored,
    reusable configuration instead of one derived on the fly from a
    hardcoded category lookup table.
    """

    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)
    category: str = Field(min_length=1, max_length=60)
    subjects: list[str] = Field(min_length=1, max_length=20)
    questionTypes: list[str] = Field(min_length=1, max_length=10)
    interviewerStyle: str = Field(default="professional", max_length=40)
    difficulty: ProfileDifficulty = "medium"
    maxQuestions: int = Field(default=8, ge=3, le=30)
    followUpEnabled: bool = True
    adaptiveDifficulty: bool = True
    resumeGrounding: bool = True
    jdGrounding: bool = True

    @field_validator("name", "category", "interviewerStyle")
    @classmethod
    def _clean_required_text(cls, value: str) -> str:
        cleaned = _clean_text(value)
        if not cleaned:
            raise ValueError("This field cannot be blank.")
        return cleaned

    @field_validator("description")
    @classmethod
    def _clean_description(cls, value: str) -> str:
        return _clean_text(value)

    @model_validator(mode="after")
    def _clean_lists(self) -> "InterviewProfileBase":
        self.subjects = _clean_items(self.subjects)
        self.questionTypes = _clean_items(self.questionTypes)
        if not self.subjects:
            raise ValueError("At least one subject is required.")
        if not self.questionTypes:
            raise ValueError("At least one question type is required.")
        return self


class InterviewProfileCreate(InterviewProfileBase):
    """Payload for POST /interview-profiles. isActive/isSystem/createdBy are
    always server-assigned, never client-settable."""


class InterviewProfileUpdate(BaseModel):
    """Payload for PATCH /interview-profiles/{id}. Every field optional —
    only what's supplied gets changed."""

    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    description: Optional[str] = Field(default=None, max_length=500)
    category: Optional[str] = Field(default=None, min_length=1, max_length=60)
    subjects: Optional[list[str]] = Field(default=None, min_length=1, max_length=20)
    questionTypes: Optional[list[str]] = Field(default=None, min_length=1, max_length=10)
    interviewerStyle: Optional[str] = Field(default=None, max_length=40)
    difficulty: Optional[ProfileDifficulty] = None
    maxQuestions: Optional[int] = Field(default=None, ge=3, le=30)
    followUpEnabled: Optional[bool] = None
    adaptiveDifficulty: Optional[bool] = None
    resumeGrounding: Optional[bool] = None
    jdGrounding: Optional[bool] = None
    isActive: Optional[bool] = None

    @model_validator(mode="before")
    @classmethod
    def _reject_explicit_nulls(cls, data):
        """Every field is optional, but *omitted* is not the same as ``null``: a
        supplied ``null`` used to be written straight into MongoDB (``name: null``,
        ``subjects: null``), after which the profile could no longer be read or
        used to start an interview."""
        if isinstance(data, dict):
            nulls = sorted(key for key, value in data.items() if value is None)
            if nulls:
                raise ValueError(f"These fields cannot be null (omit them instead): {', '.join(nulls)}.")
        return data

    @field_validator("name", "category", "interviewerStyle")
    @classmethod
    def _clean_required_text(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = _clean_text(value)
        if not cleaned:
            raise ValueError("This field cannot be blank.")
        return cleaned

    @field_validator("description")
    @classmethod
    def _clean_description(cls, value: Optional[str]) -> Optional[str]:
        return None if value is None else _clean_text(value)

    @field_validator("subjects", "questionTypes")
    @classmethod
    def _clean_list(cls, value: Optional[list[str]]) -> Optional[list[str]]:
        if value is None:
            return None
        cleaned = _clean_items(value)
        if not cleaned:
            raise ValueError("Provide at least one non-blank entry.")
        return cleaned


class InterviewProfileOut(InterviewProfileBase):
    id: str
    isActive: bool
    isSystem: bool
    createdBy: Optional[str] = None
    createdAt: datetime
    updatedAt: datetime
