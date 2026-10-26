import asyncio

import aiohttp

from config import API_MODEL, API_TOKEN, API_URL

TIMEOUT = aiohttp.ClientTimeout(total=60)


class AIError(Exception):
    """AI xizmatiga ulanib bo'lmadi yoki kutilmagan javob keldi."""


def _endpoint() -> str:
    return f"{API_URL.rstrip('/')}"


async def ask_ai(messages: list[dict[str, str]]) -> str:
    """OpenAI formatidagi chat/completions so'rovi; javob matnini qaytaradi."""
    try:
        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            async with session.post(
                _endpoint(),
                json={"messages": messages, **({"model": API_MODEL} if API_MODEL else {})},
                headers={"Authorization": f"Bearer {API_TOKEN}"},
            ) as resp:
                if resp.status != 200:
                    raise AIError(f"AI API {resp.status}: {(await resp.text())[:200]}")
                data = await resp.json(content_type=None)
    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        raise AIError(f"AI API ulanish xatosi: {e!r}") from e

    try:
        text = (data["choices"][0]["message"]["content"] or "").strip()
    except (KeyError, IndexError, TypeError) as e:
        raise AIError(f"AI API kutilmagan javob: {str(data)[:200]}") from e
    if not text:
        raise AIError("AI API bo'sh javob qaytardi")
    return text
