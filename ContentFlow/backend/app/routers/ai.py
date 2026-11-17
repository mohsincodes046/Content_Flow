from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException

from app import ai as ai_service
from app.database import Row, connect_database
from app.schemas import AIUsageResponse, CaptionDrafts, CaptionGenerationRequest, CaptionGenerationResponse
from app.security import ai_limits, check_rate_limit, count_recent_events, require_content_role

router = APIRouter()

# Overloaded (500/502/503/504) or retired model (404): worth trying the next model.
_FALLBACK_STATUSES = {404, 500, 502, 503, 504}


async def _call_with_fallback(provider: str, api_key: str, models: list[str], prompt: str) -> str:
    for index, model in enumerate(models):
        last = index == len(models) - 1
        try:
            # A busy model can hang; leave time for the fallback within one request.
            return await ai_service.call_caption_provider(provider, api_key, model, prompt, timeout=45 if last else 20)
        except httpx.HTTPStatusError as error:
            if last or error.response.status_code not in _FALLBACK_STATUSES:
                raise
        except httpx.TimeoutException:
            if last:
                raise
    raise RuntimeError("no AI model configured")  # unreachable: models is never empty


@router.post("/api/ai/captions", response_model=CaptionGenerationResponse)
async def generate_platform_captions(
    payload: CaptionGenerationRequest,
    user: Annotated[Row, Depends(require_content_role)],
) -> CaptionGenerationResponse:
    provider = os.environ.get("CONTENT_FLOW_AI_PROVIDER", "claude").strip().lower()
    # (key variable, model variable, default model, default fallback models)
    provider_config = {
        "openai": ("OPENAI_API_KEY", "OPENAI_MODEL", "gpt-5-mini", ""),
        # Google retires pinned Gemini versions for new keys and its free tier often answers
        # 503 "high demand", so use the moving alias and fall back to the lighter model.
        "gemini": ("GEMINI_API_KEY", "GEMINI_MODEL", "gemini-flash-latest", "gemini-flash-lite-latest"),
        "claude": ("ANTHROPIC_API_KEY", "CLAUDE_MODEL", "claude-sonnet-5-5", ""),
    }
    if provider not in provider_config:
        raise HTTPException(status_code=503, detail="Set CONTENT_FLOW_AI_PROVIDER to claude, openai, or gemini.")
    key_name, model_name, default_model, default_fallbacks = provider_config[provider]
    api_key = os.environ.get(key_name, "").strip()
    if not api_key:
        raise HTTPException(status_code=503, detail=f"Configure {key_name} on the backend to generate captions.")

    per_minute, per_day = ai_limits()
    check_rate_limit(
        "ai_minute", user["workspace_id"], per_minute, timedelta(minutes=1),
        detail="You are generating captions too quickly. Please wait a moment.",
    )
    # Every provider call counts toward the daily quota, because failed calls can still be billed.
    check_rate_limit(
        "ai_daily", user["workspace_id"], per_day, timedelta(days=1),
        detail=f"You have used all {per_day} AI caption generations for the last 24 hours.",
    )

    model = os.environ.get(model_name, "").strip() or default_model
    fallback_raw = os.environ.get(f"{provider.upper()}_FALLBACK_MODELS", default_fallbacks)
    models = [model] + [m for m in (s.strip() for s in fallback_raw.split(",")) if m and m != model]
    platform_guidance = {
        "instagram": "Make it visual and engaging, with a concise opening and relevant hashtags.",
        "facebook": "Make it conversational and contextual, with few hashtags and a natural invitation to respond.",
        "linkedin": "Make it professional and insight-led, with restrained industry-relevant hashtags.",
        "youtube": "Write a searchable description with a strong first sentence and a few discovery hashtags.",
        "tiktok": "Write a concise, energetic hook and a small set of discovery hashtags.",
    }
    platform_instructions = "\n".join(
        f"- {platform}: {platform_guidance[platform]}" for platform in payload.platforms
    )
    prompt = (
        "Create platform-specific social captions. Do not invent dates, prices, results, links, or other facts. "
        "Return only JSON in this shape: {\"posts\":[{\"platform\":string,\"caption\":string,\"hashtags\":[string]}]}. "
        "Hashtags must not include the leading #. Include exactly one distinct post for each requested platform.\n"
        f"Topic: {payload.topic}\nAudience: {payload.audience}\nLanguage: {payload.language}\n"
        f"Additional instructions: {payload.instructions or 'None'}\nPlatform requirements:\n{platform_instructions}"
    )
    try:
        generated_text = await _call_with_fallback(provider, api_key, models, prompt)
        generated = CaptionDrafts.model_validate_json(generated_text)
    except httpx.TimeoutException as error:
        raise HTTPException(status_code=502, detail="The AI provider timed out. Please try again.") from error
    except httpx.HTTPStatusError as error:
        code = error.response.status_code
        if code == 429:
            # Common on free tiers (e.g. Gemini's per-minute and per-day request limits).
            raise HTTPException(status_code=503, detail="The AI provider's usage limit was reached. Please try again in a minute.") from error
        if code in (401, 403):
            raise HTTPException(status_code=503, detail="The AI provider rejected the API key. Check the key on the backend.") from error
        if code in _FALLBACK_STATUSES:
            raise HTTPException(status_code=503, detail="The AI provider is busy right now. Please try again in a minute.") from error
        raise HTTPException(status_code=502, detail="The AI provider could not generate captions.") from error
    except httpx.HTTPError as error:
        raise HTTPException(status_code=502, detail="The AI provider could not generate captions.") from error
    except ValueError as error:
        raise HTTPException(status_code=502, detail="The AI provider returned invalid caption data.") from error
    except Exception as error:
        if error.__class__.__module__.startswith("pydantic"):
            raise HTTPException(status_code=502, detail="The AI provider returned captions in an invalid format.") from error
        raise

    generated_platforms = [draft.platform for draft in generated.posts]
    if set(generated_platforms) != set(payload.platforms) or len(generated_platforms) != len(payload.platforms):
        raise HTTPException(status_code=502, detail="The AI provider did not return one caption per selected platform.")
    return CaptionGenerationResponse(provider=provider, posts=generated.posts)



@router.get("/api/ai/usage", response_model=AIUsageResponse)
def ai_usage(user: Annotated[Row, Depends(require_content_role)]) -> AIUsageResponse:
    _, per_day = ai_limits()
    now = datetime.now(timezone.utc)
    with connect_database() as connection:
        used, _ = count_recent_events(connection, "ai_daily", user["workspace_id"], timedelta(days=1), now)
    return AIUsageResponse(used_last_24h=used, daily_limit=per_day, remaining=max(0, per_day - used))
