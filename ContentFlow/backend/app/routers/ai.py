from __future__ import annotations

import base64
import os
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Annotated, TypeVar

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ValidationError

from app import ai as ai_service
from app.config import env_int
from app.database import Row, connect_database
from app.schemas import (
    AIAssistItems,
    AIAssistRequest,
    AIAssistResponse,
    AIImageRequest,
    AIImageResponse,
    AIUsageResponse,
    CaptionDrafts,
    CaptionGenerationRequest,
    CaptionGenerationResponse,
)
from app.security import ai_limits, check_rate_limit, count_recent_events, require_content_role

router = APIRouter()
Parsed = TypeVar("Parsed", bound=BaseModel)

# Overloaded (500/502/503/504) or retired model (404): worth trying the next model.
_FALLBACK_STATUSES = {404, 500, 502, 503, 504}

# (key variable, model variable, default model, default fallback models)
_PROVIDERS = {
    "openai": ("OPENAI_API_KEY", "OPENAI_MODEL", "gpt-5-mini", ""),
    # Google retires pinned Gemini versions for new keys and its free tier often answers
    # 503 "high demand", so use the moving alias and fall back to the lighter model.
    "gemini": ("GEMINI_API_KEY", "GEMINI_MODEL", "gemini-flash-latest", "gemini-flash-lite-latest"),
    "claude": ("ANTHROPIC_API_KEY", "CLAUDE_MODEL", "claude-sonnet-5-5", ""),
}

PLATFORM_GUIDANCE = {
    "instagram": "visual and engaging, a strong first line (it is cut off after about 125 characters), "
                 "line breaks for readability, 3-10 relevant hashtags. Hard limit 2,200 characters.",
    "facebook": "conversational and contextual, few or no hashtags, a natural invitation to respond.",
    "linkedin": "professional and insight-led, short paragraphs, a clear takeaway, 3-5 restrained "
                "industry hashtags. Hard limit 3,000 characters.",
    "tiktok": "a punchy hook in the first words, casual and energetic, 3-6 discovery hashtags. "
              "Hard limit 2,200 characters.",
    "youtube": "a searchable description with a strong first sentence and a few discovery hashtags.",
}
TONE_GUIDANCE = {
    "friendly": "warm and approachable",
    "professional": "polished, credible and clear",
    "playful": "light, witty and fun (never at anyone's expense)",
    "inspirational": "uplifting and motivating",
    "informative": "factual, helpful and easy to scan",
    "urgent": "direct and time-sensitive, without false scarcity or invented deadlines",
}
LENGTH_GUIDANCE = {
    "short": "short: one or two sentences, under about 150 characters before hashtags",
    "medium": "medium: about 2-4 sentences",
    "long": "long-form: several short paragraphs (still within each platform's limit)",
}
FACT_RULE = ("Do not invent dates, prices, discounts, results, statistics, links, quotes or other facts that "
             "the user did not provide. Hashtags must not include the leading #.")


def _provider() -> tuple[str, str, list[str]]:
    provider = os.environ.get("CONTENT_FLOW_AI_PROVIDER", "claude").strip().lower()
    if provider not in _PROVIDERS:
        raise HTTPException(status_code=503, detail="Set CONTENT_FLOW_AI_PROVIDER to claude, openai, or gemini.")
    key_name, model_name, default_model, default_fallbacks = _PROVIDERS[provider]
    api_key = os.environ.get(key_name, "").strip()
    if not api_key:
        raise HTTPException(status_code=503, detail=f"Configure {key_name} on the backend to generate captions.")
    model = os.environ.get(model_name, "").strip() or default_model
    fallback_raw = os.environ.get(f"{provider.upper()}_FALLBACK_MODELS", default_fallbacks)
    models = [model] + [m for m in (s.strip() for s in fallback_raw.split(",")) if m and m != model]
    return provider, api_key, models


def _charge_text_generation(user: Row) -> None:
    per_minute, per_day = ai_limits()
    check_rate_limit(
        "ai_minute", user["workspace_id"], per_minute, timedelta(minutes=1),
        detail="You are generating content too quickly. Please wait a moment.",
    )
    # Every provider call counts toward the daily quota, because failed calls can still be billed.
    check_rate_limit(
        "ai_daily", user["workspace_id"], per_day, timedelta(days=1),
        detail=f"You have used all {per_day} AI generations for the last 24 hours.",
    )


async def _call_with_fallback(provider: str, api_key: str, models: list[str], prompt: str,
                              user_message: str = ai_service.DEFAULT_USER_MESSAGE) -> str:
    for index, model in enumerate(models):
        last = index == len(models) - 1
        try:
            # A busy model can hang; leave time for the fallback within one request.
            return await ai_service.call_caption_provider(provider, api_key, model, prompt,
                                                          timeout=45 if last else 20, user_message=user_message)
        except httpx.HTTPStatusError as error:
            # Gemini's free-tier quotas are per model, so a 429 on one may still leave the next.
            if last or error.response.status_code not in _FALLBACK_STATUSES | {429}:
                raise
        except httpx.TimeoutException:
            if last:
                raise
    raise RuntimeError("no AI model configured")  # unreachable: models is never empty


def _provider_error(error: Exception) -> HTTPException:
    """A clear, user-facing message for each way a provider call can fail."""
    if isinstance(error, httpx.TimeoutException):
        return HTTPException(status_code=502, detail="The AI provider timed out. Please try again.")
    if isinstance(error, httpx.HTTPStatusError):
        code = error.response.status_code
        if code == 429:
            # Common on free tiers (e.g. Gemini's per-minute and per-day request limits).
            return HTTPException(status_code=503, detail="The AI provider's usage limit was reached. Please try again in a minute.")
        if code in (401, 403):
            return HTTPException(status_code=503, detail="The AI provider rejected the API key. Check the key on the backend.")
        if code in _FALLBACK_STATUSES:
            return HTTPException(status_code=503, detail="The AI provider is busy right now. Please try again in a minute.")
    if isinstance(error, (ValidationError, ValueError)):
        return HTTPException(status_code=502, detail="The AI provider returned content in an invalid format. Please try again.")
    return HTTPException(status_code=502, detail="The AI provider could not generate content.")


async def _generate(prompt: str, schema: type[Parsed], user_message: str = ai_service.DEFAULT_USER_MESSAGE) -> tuple[str, Parsed]:
    provider, api_key, models = _provider()
    try:
        text = await _call_with_fallback(provider, api_key, models, prompt, user_message)
        return provider, schema.model_validate_json(_strip_code_fence(text))
    except (httpx.HTTPError, ValueError, ValidationError) as error:
        raise _provider_error(error) from error


def _strip_code_fence(text: str) -> str:
    """Some models wrap JSON in ```json fences despite being asked not to."""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.split("\n", 1)[1] if "\n" in stripped else ""
        stripped = stripped.rsplit("```", 1)[0]
    return stripped.strip()


def _platform_lines(platforms: list[str]) -> str:
    return "\n".join(f"- {p}: {PLATFORM_GUIDANCE[p]}" for p in platforms)


@router.post("/api/ai/captions", response_model=CaptionGenerationResponse)
async def generate_platform_captions(
    payload: CaptionGenerationRequest,
    user: Annotated[Row, Depends(require_content_role)],
) -> CaptionGenerationResponse:
    _provider()  # fail fast on configuration before using quota
    _charge_text_generation(user)
    cta_rule = ("End each caption with one clear call to action that fits the platform, and also return it alone "
                "in call_to_action." if payload.include_call_to_action else
                "Do not add a call to action; return call_to_action as an empty string.")
    prompt = (
        "Create platform-specific social media captions. " + FACT_RULE + " "
        "Return only JSON in this shape: {\"posts\":[{\"platform\":string,\"variant\":number,\"caption\":string,"
        "\"hashtags\":[string],\"call_to_action\":string}]}. "
        f"Write exactly {payload.variations} clearly different variation(s) for each requested platform, "
        f"numbered with variant 1 to {payload.variations}. Put hashtags only in the hashtags list, not in the caption.\n"
        f"Tone: {TONE_GUIDANCE[payload.tone]}.\nLength: {LENGTH_GUIDANCE[payload.length]}.\n{cta_rule}\n"
        f"Topic: {payload.topic}\nAudience: {payload.audience}\nLanguage: {payload.language}\n"
        f"Additional instructions and verified facts: {payload.instructions or 'None'}\n"
        f"Platform requirements:\n{_platform_lines(payload.platforms)}"
    )
    provider, generated = await _generate(prompt, CaptionDrafts)
    counts = Counter(draft.platform for draft in generated.posts)
    if set(counts) != set(payload.platforms) or any(n != payload.variations for n in counts.values()):
        raise HTTPException(status_code=502, detail="The AI provider did not return the requested captions for every platform. Please try again.")
    for platform in payload.platforms:  # number variants 1..n regardless of what the model wrote
        for number, draft in enumerate((d for d in generated.posts if d.platform == platform), start=1):
            draft.variant = number
    return CaptionGenerationResponse(provider=provider, posts=generated.posts)


_TASKS = {
    "ideas": ("Suggest {count} distinct, specific post ideas about the topic below. For each idea give a short "
              "title, a 1-2 sentence description of the post in text, and the platform it suits best "
              "(one of the requested platforms) in platform.", "{count} ideas"),
    "rewrite": ("Rewrite the content below {count} different ways in the requested tone and length, keeping its "
                "meaning and every fact unchanged. Leave platform empty; give each a short title naming the angle.",
                "{count} rewrites"),
    "repurpose": ("Repurpose the content below into one ready-to-post version for EACH requested platform, adapted "
                  "to that platform's format and limits. Set platform on every item and include suitable hashtags.",
                  "one item per platform"),
    "hashtags": ("Suggest one hashtag set for EACH requested platform (set platform). Put 8-15 hashtags for "
                 "Instagram, 3-6 for TikTok and 3-5 for LinkedIn and Facebook in hashtags. text must NOT be a caption: "
                 "it is only a one-line note (under 120 characters) on why this mix works.", "one hashtag set per platform"),
    "call_to_action": ("Write {count} distinct calls to action for the content below. text must be ONLY the call to "
                       "action: one short sentence under 120 characters, not a caption, for example "
                       "\"Tag a friend you'd share this with.\" (write your own, specific to the content). Set title to the platform it suits and leave hashtags "
                       "empty. Do not promise offers, prices or deadlines that are not in the content.",
                       "{count} one-sentence calls to action"),
    "description": ("Write a post description for EACH requested platform (set platform) based on the content below: "
                    "a clear, searchable description of what the post or video shows, with relevant hashtags.",
                    "one item per platform"),
}


# Hashtag sets and calls to action have their own fixed size.
_SIZED_TASKS = {"ideas", "rewrite", "repurpose", "description"}


@router.post("/api/ai/assist", response_model=AIAssistResponse)
async def ai_assist(
    payload: AIAssistRequest,
    user: Annotated[Row, Depends(require_content_role)],
) -> AIAssistResponse:
    _provider()
    _charge_text_generation(user)
    instruction, expected = _TASKS[payload.task]
    prompt = (
        "You help a social media team create content. " + FACT_RULE + " "
        "Return only JSON in this shape: {\"items\":[{\"platform\":string or null,\"title\":string,\"text\":string,"
        "\"hashtags\":[string]}]}.\n"
        f"Tone: {TONE_GUIDANCE[payload.tone]}.\n"
        + (f"Length: {LENGTH_GUIDANCE[payload.length]}.\n" if payload.task in _SIZED_TASKS else "")
        + f"Language: {payload.language}\nAudience: {payload.audience or 'General followers'}\n"
        # Caption-style platform notes pull a call to action towards a full caption.
        + (f"Requested platforms: {', '.join(payload.platforms)}\n" if payload.task == "call_to_action"
           else f"Requested platforms:\n{_platform_lines(payload.platforms)}\n")
        + f"{'Topic' if payload.task == 'ideas' else 'Content'}:\n{payload.text}\n\n"
        # Last, so it outweighs the platform notes above.
        f"Task: {instruction.format(count=payload.count)}"
    )
    provider, generated = await _generate(
        prompt, AIAssistItems, user_message=f"Return {expected.format(count=payload.count)} as the requested JSON only.",
    )
    allowed = set(payload.platforms)
    items = [item for item in generated.items if item.platform is None or item.platform in allowed]
    if payload.task in ("repurpose", "description"):
        if {item.platform for item in items} != allowed:
            raise HTTPException(status_code=502, detail="The AI provider did not return a version for every platform. Please try again.")
    if not items:
        raise HTTPException(status_code=502, detail="The AI provider returned nothing usable. Please try again.")
    return AIAssistResponse(provider=provider, task=payload.task, items=items)


def _image_settings() -> tuple[str, str] | None:
    """Image generation runs only when an image model is configured (Gemini)."""
    model = os.environ.get("CONTENT_FLOW_AI_IMAGE_MODEL", "").strip()
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    return (api_key, model) if model and api_key else None


def _image_daily_limit() -> int:
    return env_int("CONTENT_FLOW_AI_IMAGE_DAILY_LIMIT", 10)


@router.post("/api/ai/image", response_model=AIImageResponse)
async def ai_image(
    payload: AIImageRequest,
    user: Annotated[Row, Depends(require_content_role)],
) -> AIImageResponse:
    settings = _image_settings()
    if settings is None:
        raise HTTPException(status_code=503, detail="AI image generation is not set up on this server. "
                            "An administrator can enable it with CONTENT_FLOW_AI_IMAGE_MODEL and GEMINI_API_KEY.")
    per_minute, _ = ai_limits()
    check_rate_limit("ai_minute", user["workspace_id"], per_minute, timedelta(minutes=1),
                     detail="You are generating content too quickly. Please wait a moment.")
    limit = _image_daily_limit()
    check_rate_limit("ai_image_daily", user["workspace_id"], limit, timedelta(days=1),
                     detail=f"You have used all {limit} AI images for the last 24 hours.")
    api_key, model = settings
    prompt = (f"Create a high-quality social media image. {payload.prompt.strip()}\n"
              "Do not include any text, logos or watermarks unless the description asks for them.")
    try:
        media_type, data = await ai_service.generate_image(api_key, model, prompt, payload.aspect_ratio)
    except (httpx.HTTPError, ValueError) as error:
        raise _provider_error(error) from error
    if not media_type.startswith("image/"):
        raise HTTPException(status_code=502, detail="The AI provider returned an unexpected file type.")
    return AIImageResponse(media_type=media_type, data_base64=base64.b64encode(data).decode("ascii"))


@router.get("/api/ai/usage", response_model=AIUsageResponse)
def ai_usage(user: Annotated[Row, Depends(require_content_role)]) -> AIUsageResponse:
    _, per_day = ai_limits()
    now = datetime.now(timezone.utc)
    with connect_database() as connection:
        used, _ = count_recent_events(connection, "ai_daily", user["workspace_id"], timedelta(days=1), now)
        images, _ = count_recent_events(connection, "ai_image_daily", user["workspace_id"], timedelta(days=1), now)
    enabled = _image_settings() is not None
    return AIUsageResponse(used_last_24h=used, daily_limit=per_day, remaining=max(0, per_day - used),
                           image_generation_enabled=enabled, images_used_last_24h=images,
                           image_daily_limit=_image_daily_limit() if enabled else 0)
