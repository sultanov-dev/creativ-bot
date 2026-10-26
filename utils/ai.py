import asyncio
from urllib.parse import urlsplit

import aiohttp

from config import API_MODEL, API_TOKEN, API_URL

TIMEOUT = aiohttp.ClientTimeout(total=60)


class AIError(Exception):
    """AI xizmatiga ulanib bo'lmadi yoki kutilmagan javob keldi."""


# javob uzunligi (va xarajat) chegarasi
MAX_TOKENS = 1500
_LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")


def _endpoint() -> str:
    url = API_URL.rstrip("/")
    parts = urlsplit(url)
    # Bearer token ochiq (http) kanalda ketmasligi uchun
    if parts.scheme != "https" and parts.hostname not in _LOCAL_HOSTS:
        raise AIError("API_URL https:// bilan boshlanishi kerak")
    return url


async def ask_ai(messages: list[dict[str, str]]) -> str:
    """OpenAI formatidagi chat/completions so'rovi; javob matnini qaytaradi."""
    try:
        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            async with session.post(
                _endpoint(),
                json={
                    "messages": messages,
                    "max_tokens": MAX_TOKENS,
                    **({"model": API_MODEL} if API_MODEL else {}),
                },
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
