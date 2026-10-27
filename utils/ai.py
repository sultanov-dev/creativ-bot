import asyncio
from urllib.parse import urlsplit

import aiohttp

from config import API_MODEL, API_TOKEN, API_URL

TIMEOUT = aiohttp.ClientTimeout(total=60)


class AIError(Exception):
    """AI xizmatiga ulanib bo'lmadi yoki kutilmagan javob keldi."""


# javob uzunligi (va xarajat) chegarasi; uzun javob = uzoq kutish, shuning uchun o'rtacha
MAX_TOKENS = 900
_LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")


def _endpoint() -> str:
    url = API_URL.rstrip("/")
    parts = urlsplit(url)
    # Bearer token ochiq (http) kanalda ketmasligi uchun
    if parts.scheme != "https" and parts.hostname not in _LOCAL_HOSTS:
        raise AIError("API_URL https:// bilan boshlanishi kerak")
    return url


_session: aiohttp.ClientSession | None = None
_session_loop: asyncio.AbstractEventLoop | None = None


def _get_session() -> aiohttp.ClientSession:
    """Umumiy sessiya: ulanish (TLS) qayta-qayta o'rnatilmaydi, har so'rov ~0,3-0,5 s tezroq."""
    global _session, _session_loop
    loop = asyncio.get_running_loop()
    if _session is None or _session.closed or _session_loop is not loop:
        _session = aiohttp.ClientSession(timeout=TIMEOUT)
        _session_loop = loop
    return _session


async def close_session() -> None:
    """Bot to'xtaganda chaqiriladi."""
    global _session
    if _session is not None and not _session.closed:
        await _session.close()
    _session = None


async def ask_ai(messages: list[dict[str, str]]) -> str:
    """OpenAI formatidagi chat/completions so'rovi; javob matnini qaytaradi."""
    try:
        async with _get_session().post(
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
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as e:  # ValueError: JSON emas
        raise AIError(f"AI API ulanish xatosi: {e!r}") from e

    try:
        text = (data["choices"][0]["message"]["content"] or "").strip()
    except (KeyError, IndexError, TypeError) as e:
        raise AIError(f"AI API kutilmagan javob: {str(data)[:200]}") from e
    if not text:
        raise AIError("AI API bo'sh javob qaytardi")
    return text
