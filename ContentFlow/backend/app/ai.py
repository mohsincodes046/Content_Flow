from __future__ import annotations

import httpx


async def call_caption_provider(provider: str, api_key: str, model: str, prompt: str, timeout: float = 45) -> str:
    async with httpx.AsyncClient(timeout=timeout) as client:
        if provider == "openai":
            response = await client.post(
                "https://api.openai.com/v1/responses",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": model,
                    "instructions": prompt,
                    "input": "Generate one distinct post for each requested platform.",
                    "text": {"format": {"type": "json_object"}},
                },
            )
        elif provider == "gemini":
            response = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                headers={"x-goog-api-key": api_key},
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"responseMimeType": "application/json"},
                },
            )
        else:
            response = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                },
                json={
                    "model": model,
                    "max_tokens": 1500,
                    "system": prompt,
                    "messages": [{
                        "role": "user",
                        "content": "Generate one distinct post for each requested platform and return only the requested JSON.",
                    }],
                },
            )
        response.raise_for_status()
        result = response.json()

    if provider == "openai":
        text = result.get("output_text")
        if not isinstance(text, str):
            text = "".join(
                part["text"]
                for item in result.get("output", [])
                for part in item.get("content", [])
                if isinstance(part, dict) and isinstance(part.get("text"), str)
            )
    elif provider == "gemini":
        text = "".join(
            part["text"]
            for candidate in result.get("candidates", [])
            for part in candidate.get("content", {}).get("parts", [])
            if isinstance(part, dict) and isinstance(part.get("text"), str)
        )
    else:
        text = "".join(
            block["text"]
            for block in result.get("content", [])
            if isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str)
        )
    if not text:
        raise ValueError("The AI provider returned no caption text.")
    return text
