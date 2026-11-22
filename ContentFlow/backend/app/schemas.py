from __future__ import annotations

# `date` and `time` look unused because fields share their names, but Pydantic
# resolves the string annotations (e.g. `date: date`) from this module's globals.
from datetime import date, time  # noqa: F401
from datetime import datetime as datetime_type
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

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


AITone = Literal["friendly", "professional", "playful", "inspirational", "informative", "urgent"]
AILength = Literal["short", "medium", "long"]


class CaptionGenerationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic: str = Field(min_length=1, max_length=500)
    audience: str = Field(min_length=1, max_length=300)
    instructions: str = Field(default="", max_length=2000)
    language: str = Field(default="English", min_length=1, max_length=60)
    platforms: list[Platform] = Field(min_length=1, max_length=5)
    tone: AITone = "friendly"
    length: AILength = "medium"
    variations: int = Field(default=1, ge=1, le=3)
    include_call_to_action: bool = True

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
    call_to_action: str = Field(default="", max_length=300)
    variant: int = 1  # renumbered by the API; a model's own numbering is not trusted


class CaptionDrafts(BaseModel):
    posts: list[CaptionDraft] = Field(min_length=1, max_length=15)


AIAssistTask = Literal["ideas", "rewrite", "repurpose", "hashtags", "call_to_action", "description"]


class AIAssistRequest(BaseModel):
    """One of the content tools. `text` is the topic (ideas) or the content to work on."""
    model_config = ConfigDict(extra="forbid")

    task: AIAssistTask
    text: str = Field(min_length=1, max_length=5000)
    audience: str = Field(default="", max_length=300)
    platforms: list[Platform] = Field(min_length=1, max_length=5)
    tone: AITone = "friendly"
    length: AILength = "medium"
    language: str = Field(default="English", min_length=1, max_length=60)
    count: int = Field(default=3, ge=1, le=5)

    @field_validator("text", "audience", "language", mode="before")
    @classmethod
    def strip_text(cls, value: object) -> str:
        if not isinstance(value, str):
            raise ValueError("Text fields must be strings.")
        return value.strip()

    @field_validator("platforms")
    @classmethod
    def unique_platforms(cls, value: list[Platform]) -> list[Platform]:
        if len(value) != len(set(value)):
            raise ValueError("Each platform can only be selected once.")
        return value


class AIAssistItem(BaseModel):
    platform: Optional[Platform] = None
    title: str = Field(default="", max_length=200)
    text: str = Field(min_length=1, max_length=5000)
    hashtags: list[str] = Field(default_factory=list, max_length=30)


class AIAssistItems(BaseModel):
    items: list[AIAssistItem] = Field(min_length=1, max_length=25)


class AIAssistResponse(BaseModel):
    provider: Literal["openai", "gemini", "claude"]
    task: AIAssistTask
    items: list[AIAssistItem]


class AIImageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: str = Field(min_length=3, max_length=2000)
    aspect_ratio: Literal["1:1", "4:5", "9:16", "16:9"] = "1:1"


class AIImageResponse(BaseModel):
    media_type: str
    data_base64: str


class CaptionGenerationResponse(BaseModel):
    provider: Literal["openai", "gemini", "claude"]
    posts: list[CaptionDraft]


class RegistrationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: str = Field(min_length=1, max_length=100)
    # Required unless joining an existing workspace through an invitation.
    workspace_name: Optional[str] = Field(default=None, max_length=120)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    invitation_token: Optional[str] = Field(default=None, min_length=20, max_length=200)

    @field_validator("full_name", mode="before")
    @classmethod
    def strip_required_text(cls, value: object) -> str:
        if not isinstance(value, str):
            raise ValueError("This field must be text.")
        value = value.strip()
        if not value:
            raise ValueError("This field cannot be blank.")
        return value

    @field_validator("workspace_name", mode="before")
    @classmethod
    def strip_workspace_name(cls, value: object) -> Optional[str]:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("This field must be text.")
        return value.strip() or None

    @model_validator(mode="after")
    def need_workspace_or_invitation(self) -> "RegistrationCreate":
        if not self.workspace_name and not self.invitation_token:
            raise ValueError("Enter a workspace name.")
        return self


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
    width: Optional[int] = None
    height: Optional[int] = None
    created_at: Optional[str] = None
    used_by_posts: int = 0


PostStatus = Literal[
    "draft", "in_review", "changes_requested", "approved", "rejected",
    "scheduled", "publishing", "published", "partially_published", "failed",
]
TargetStatus = Literal["pending", "queued", "publishing", "published", "failed", "cancelled"]


class PostTargetInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    social_account_id: str
    caption_override: Optional[str] = Field(default=None, max_length=63206)


class PostSchedule(BaseModel):
    """A wall-clock time in an IANA timezone, e.g. 2026-12-01 09:30 in Asia/Karachi."""

    model_config = ConfigDict(extra="forbid")

    local_datetime: datetime_type = Field(description="Local date and time, without an offset")
    timezone: str = Field(min_length=1, max_length=64)


class PostWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(default="", max_length=200)
    caption: str = Field(default="", max_length=63206)
    asset_ids: list[str] = Field(default_factory=list, max_length=20)
    targets: list[PostTargetInput] = Field(default_factory=list, max_length=50)
    planned_platforms: list[Platform] = Field(default_factory=list, max_length=5)
    schedule: Optional[PostSchedule] = None

    @field_validator("asset_ids")
    @classmethod
    def unique_assets(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("Each media item can only be added once.")
        return value

    @field_validator("targets")
    @classmethod
    def unique_targets(cls, value: list[PostTargetInput]) -> list[PostTargetInput]:
        ids = [target.social_account_id for target in value]
        if len(ids) != len(set(ids)):
            raise ValueError("Each account can only be selected once.")
        return value


class PostCreate(PostWrite):
    action: Literal["draft", "schedule", "submit"] = "draft"
    reviewer_user_id: Optional[str] = None


class PostBulkCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    posts: list[PostCreate] = Field(min_length=1, max_length=366)


class PostSubmit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reviewer_user_id: str
    message: str = Field(default="", max_length=2000)


class PostReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approve", "reject", "request_changes"]
    comment: str = Field(default="", max_length=2000)


class PostComment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=2000)


class PostScheduleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schedule: PostSchedule


class PostTargetResponse(BaseModel):
    id: str
    social_account_id: Optional[str]
    platform: str
    account_name: str
    caption_override: Optional[str] = None
    status: TargetStatus
    attempts: int
    next_attempt_at: Optional[str] = None
    last_error: Optional[str] = None
    external_id: Optional[str] = None
    external_url: Optional[str] = None
    published_at: Optional[str] = None
    account_status: Optional[str] = None


class PostEventResponse(BaseModel):
    id: str
    kind: str
    message: Optional[str] = None
    actor_name: Optional[str] = None
    created_at: str


class ValidationIssue(BaseModel):
    platform: str
    account: Optional[str] = None
    message: str


class PostResponse(BaseModel):
    id: str
    title: str
    caption: str
    status: PostStatus
    scheduled_at: Optional[str] = None
    timezone: Optional[str] = None
    planned_platforms: list[str] = Field(default_factory=list)
    reviewer_user_id: Optional[str] = None
    reviewer_name: Optional[str] = None
    created_by_name: Optional[str] = None
    created_at: str
    updated_at: str
    media: list[AssetResponse] = Field(default_factory=list)
    targets: list[PostTargetResponse] = Field(default_factory=list)
    issues: list[ValidationIssue] = Field(default_factory=list)
    events: list[PostEventResponse] = Field(default_factory=list)


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


Role = Literal["owner", "admin", "editor", "client"]
InvitableRole = Literal["admin", "editor", "client"]


class WorkspaceSummary(BaseModel):
    id: str
    name: str
    role: Role


class SessionResponse(BaseModel):
    id: str
    email: str
    full_name: str
    workspace_id: Optional[str] = None
    workspace_name: Optional[str] = None
    role: Optional[Role] = None
    workspaces: list[WorkspaceSummary] = Field(default_factory=list)


class WorkspaceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, value: object) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Workspace name cannot be blank.")
        return value.strip()


class WorkspaceRename(WorkspaceCreate):
    pass


class MemberResponse(BaseModel):
    user_id: str
    full_name: str
    email: str
    role: Role
    joined_at: str


class MemberRoleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: InvitableRole


class InvitationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    role: InvitableRole


class InvitationResponse(BaseModel):
    id: str
    email: str
    role: InvitableRole
    created_at: str
    expires_at: str
    invite_url: Optional[str] = None  # only returned once, when the invitation is created


class InvitationAccept(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=20, max_length=200)


class InvitationPreview(BaseModel):
    workspace_name: str
    email: str
    role: InvitableRole


class OwnershipTransfer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str


class SocialAccountResponse(BaseModel):
    id: str
    platform: Platform
    account_id: str
    account_name: str
    account_type: str
    connected_at: str
    expires_at: Optional[str]
    status: Literal["active", "needs_reconnect"] = "active"
    last_error: Optional[str] = None
    last_checked_at: Optional[str] = None
    profile_picture_url: Optional[str] = None
    parent_account_id: Optional[str] = None
    can_publish: Optional[bool] = None
    followers_count: Optional[int] = None
    linked_page_name: Optional[str] = None


class ConnectionCandidate(BaseModel):
    key: str                      # "<platform>:<account_id>"
    platform: Platform
    account_id: str
    account_name: str
    account_type: str
    profile_picture_url: Optional[str] = None
    linked_page_name: Optional[str] = None
    followers_count: Optional[int] = None
    can_publish: bool = True
    already_connected: bool = False


class PendingConnection(BaseModel):
    id: str
    provider: str
    signed_in_as: Optional[str] = None
    candidates: list[ConnectionCandidate]


class ConnectionSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    keys: list[str] = Field(min_length=1, max_length=200)


class SocialProviderStatus(BaseModel):
    provider: Literal["meta", "tiktok", "linkedin", "youtube"]
    configured: bool
    accounts: list[SocialAccountResponse]
    publisher_enabled: bool = False



class AIUsageResponse(BaseModel):
    used_last_24h: int
    daily_limit: int
    remaining: int
    image_generation_enabled: bool = False
    images_used_last_24h: int = 0
    image_daily_limit: int = 0
