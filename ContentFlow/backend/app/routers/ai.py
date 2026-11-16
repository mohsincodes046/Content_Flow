from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException

from app import ai as ai_service
from app.database import connect_database
from app.schemas import AIUsageResponse, CaptionDrafts, CaptionGenerationRequest, CaptionGenerationResponse
from app.security import ai_limits, check_rate_limit, count_recent_events, get_current_user

router = APIRouter()


@router.post("/api/ai/captions", response_model=CaptionGenerationResponse)
async def generate_platform_captions(
    payload: CaptionGenerationRequest,
    user: Annotated[sqlite3.Row, Depends(get_current_user)],
) -> CaptionGenerationResponse:
    provider = os.environ.get("CONTENT_FLOW_AI_PROVIDER", "claude").strip().lower()
    provider_config = {
        "openai": ("OPENAI_API_KEY", "OPENAI_MODEL", "gpt-5-mini"),
        "gemini": ("GEMINI_API_KEY", "GEMINI_MODEL", "gemini-2.5-flash"),
        "claude": ("ANTHROPIC_API_KEY", "CLAUDE_MODEL", "claude-sonnet-5-5"),
    }
    if provider not in provider_config:
        raise HTTPException(status_code=503, detail="Set CONTENT_FLOW_AI_PROVIDER to claude, openai, or gemini.")
    key_name, model_name, default_model = provider_config[provider]
    api_key = os.environ.get(key_name, "").strip()
    if not api_key:
        raise HTTPException(status_code=503, detail=f"Configure {key_name} on the backend to generate captions.")

    per_minute, per_day = ai_limits()
    check_rate_limit(
        "ai_minute", user["id"], per_minute, timedelta(minutes=1),
        detail="You are generating captions too quickly. Please wait a moment.",
    )
    # Every provider call counts toward the daily quota, because failed calls can still be billed.
    check_rate_limit(
        "ai_daily", user["id"], per_day, timedelta(days=1),
        detail=f"You have used all {per_day} AI caption generations for the last 24 hours.",
    )

    model = os.environ.get(model_name, default_model).strip()
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
        generated_text = await ai_service.call_caption_provider(provider, api_key, model, prompt)
        generated = CaptionDrafts.model_validate_json(generated_text)
    except httpx.TimeoutException as error:
        raise HTTPException(status_code=502, detail="The AI provider timed out. Please try again.") from error
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
def ai_usage(user: Annotated[sqlite3.Row, Depends(get_current_user)]) -> AIUsageResponse:
    _, per_day = ai_limits()
    now = datetime.now(timezone.utc)
    with connect_database() as connection:
        used, _ = count_recent_events(connection, "ai_daily", user["id"], timedelta(days=1), now)
    return AIUsageResponse(used_last_24h=used, daily_limit=per_day, remaining=max(0, per_day - used))
