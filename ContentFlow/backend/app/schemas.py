from __future__ import annotations

# `date` and `time` look unused because fields share their names, but Pydantic
# resolves the string annotations (e.g. `date: date`) from this module's globals.
from datetime import date, time  # noqa: F401
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.config import Platform


class SubmissionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    campaign: str = Field(default="", max_length=100)
    audience: str = Field(min_length=1, max_length=160)
    instructions: str = Field(min_length=1, max_length=2000)
    language: str = Field(min_length=1, max_length=60)
    platforms: list[Platform] = Field(min_length=1, max_length=5)
    asset_ids: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("campaign", "audience", "instructions", "language", mode="before")
    @classmethod
    def strip_text_fields(cls, value: object) -> str:
        if not isinstance(value, str):
            raise ValueError("Text fields must be strings.")
        return value.strip()

    @field_validator("platforms")
    @classmethod
    def reject_duplicate_platforms(cls, value: list[Platform]) -> list[Platform]:
        if len(value) != len(set(value)):
            raise ValueError("Each platform can only be selected once.")
        return value

    @field_validator("asset_ids")
    @classmethod
    def reject_duplicate_assets(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("Each uploaded asset can only be attached once.")
        return value


class CaptionGenerationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic: str = Field(min_length=1, max_length=500)
    audience: str = Field(min_length=1, max_length=300)
    instructions: str = Field(default="", max_length=2000)
    language: str = Field(default="English", min_length=1, max_length=60)
    platforms: list[Platform] = Field(min_length=1, max_length=5)

    @field_validator("topic", "audience", "instructions", "language", mode="before")
    @classmethod
    def strip_caption_text(cls, value: object) -> str:
        if not isinstance(value, str):
            raise ValueError("Text fields must be strings.")
        return value.strip()

    @field_validator("platforms")
    @classmethod
    def reject_duplicate_caption_platforms(cls, value: list[Platform]) -> list[Platform]:
        if len(value) != len(set(value)):
            raise ValueError("Each platform can only be selected once.")
        return value


class CaptionDraft(BaseModel):
    platform: Platform
    caption: str = Field(min_length=1, max_length=5000)
    hashtags: list[str] = Field(max_length=15)


class CaptionDrafts(BaseModel):
    posts: list[CaptionDraft] = Field(min_length=1, max_length=5)


class CaptionGenerationResponse(BaseModel):
    provider: Literal["openai", "gemini", "claude"]
    posts: list[CaptionDraft]


class RegistrationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: str = Field(min_length=1, max_length=100)
    workspace_name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)

    @field_validator("full_name", "workspace_name", mode="before")
    @classmethod
    def strip_required_text(cls, value: object) -> str:
        if not isinstance(value, str):
            raise ValueError("This field must be text.")
        value = value.strip()
        if not value:
            raise ValueError("This field cannot be blank.")
        return value


class LoginCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class PasswordChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class ScheduledPostCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    media_name: str = Field(min_length=1, max_length=255)
    date: date
    time: time
    platforms: list[Platform] = Field(min_length=1, max_length=5)
    caption: str = Field(default="", max_length=5000)
    asset_id: Optional[str] = None
    facebook_account_id: Optional[str] = None
    timezone_offset_minutes: int = Field(default=0, ge=-840, le=840)

    @field_validator("media_name", mode="before")
    @classmethod
    def strip_media_name(cls, value: object) -> str:
        if not isinstance(value, str):
            raise ValueError("Media name must be text.")
        value = value.strip()
        if not value:
            raise ValueError("Media name cannot be blank.")
        return value

    @field_validator("time")
    @classmethod
    def require_local_minute_precision(cls, value: time) -> time:
        if value.second or value.microsecond or value.tzinfo is not None:
            raise ValueError("Scheduled times must use local hours and minutes.")
        return value

    @field_validator("platforms")
    @classmethod
    def reject_duplicate_scheduled_platforms(
        cls,
        value: list[Platform],
    ) -> list[Platform]:
        if len(value) != len(set(value)):
            raise ValueError("Each platform can only be selected once.")
        return value


class ScheduledPostBatchCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    posts: list[ScheduledPostCreate] = Field(min_length=1, max_length=366)


class ScheduledPostDateUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date: date


class ScheduledPostResponse(BaseModel):
    id: str
    media_name: str
    date: str
    time: str
    platforms: list[Platform]
    caption: str
    asset_id: Optional[str] = None
    facebook_account_id: Optional[str] = None
    publish_status: Literal["scheduled", "publishing", "published", "failed"] = "scheduled"
    publish_error: Optional[str] = None


class AssetResponse(BaseModel):
    id: str
    filename: str
    media_type: str
    size: int


class SubmissionResponse(BaseModel):
    id: str
    campaign: str
    audience: str
    instructions: str
    language: str
    platforms: list[Platform]
    assets: list[AssetResponse]
    status: Literal["submitted"]
    created_at: str


class SessionResponse(BaseModel):
    id: str
    email: str
    full_name: str
    workspace_name: str


class SocialAccountResponse(BaseModel):
    id: str
    platform: Platform
    account_id: str
    account_name: str
    account_type: str
    connected_at: str
    expires_at: Optional[str]


class SocialProviderStatus(BaseModel):
    provider: Literal["meta", "tiktok", "linkedin", "youtube"]
    configured: bool
    accounts: list[SocialAccountResponse]
    publisher_enabled: bool = False



class AIUsageResponse(BaseModel):
    used_last_24h: int
    daily_limit: int
    remaining: int
