import asyncio
import json
import logging
from urllib.parse import urlsplit

import aiohttp

from config import API_MODEL, API_TOKEN, API_URL

logger = logging.getLogger(__name__)

# sock_connect: ulanish osilib qolsa, qayta urinishga tez o'tish uchun (butun so'rov uchun total)
TIMEOUT = aiohttp.ClientTimeout(total=60, sock_connect=8)
# ulanish xatosi, vaqtinchalik server xatosi (5xx) yoki 429 bo'lsa, shuncha marta urinadi; faqat hammasi muvaffaqiyatsiz
# bo'lsa AIError ko'tariladi (guruhga xato xabari va dasturchiga ogohlantirish shundan keyingina ketadi)
ATTEMPTS = 5
RETRY_DELAYS = (0.3, 0.6, 1.2, 2.0)  # urinishlar orasidagi kutish (soniya)
RETRY_STATUSES = (429, 500, 502, 503, 504)


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


class _Retryable(Exception):
    """Vaqtinchalik server xatosi (5xx, 429): qayta uriniladi."""


async def _post(payload: dict, attempts: int | None = None) -> dict:
    """chat/completions so'rovi; javobning JSON'ini qaytaradi. Vaqtinchalik xatolarda ATTEMPTS martagacha urinadi."""
    url = _endpoint()  # sessiyadan oldin: noto'g'ri URL bo'lsa, ortiqcha sessiya ochilmasin
    body = {**payload, **({"model": API_MODEL} if API_MODEL else {})}
    total = attempts or ATTEMPTS
    last: Exception | None = None
    for attempt in range(1, total + 1):
        try:
            async with _get_session().post(
                url, json=body, headers={"Authorization": f"Bearer {API_TOKEN}"}
            ) as resp:
                if resp.status in RETRY_STATUSES:
                    raise _Retryable(f"AI API {resp.status}: {(await resp.text())[:200]}")
                if resp.status != 200:
                    raise AIError(f"AI API {resp.status}: {(await resp.text())[:200]}")  # sozlama xatosi: qayta urinish befoyda
                return await resp.json(content_type=None)
        except (_Retryable, aiohttp.ClientConnectionError, aiohttp.ConnectionTimeoutError) as e:
            last = e
            if attempt < total:
                logger.warning("AI API urinish %s/%s muvaffaqiyatsiz: %r", attempt, total, e)
                await asyncio.sleep(RETRY_DELAYS[min(attempt, len(RETRY_DELAYS)) - 1])
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as e:  # ValueError: JSON emas
            raise AIError(f"AI API ulanish xatosi: {e!r}") from e
    raise AIError(f"AI API {total} urinishdan keyin ham javob bermadi: {last!r}") from last


def _message(data: dict) -> dict:
    try:
        message = data["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as e:
        raise AIError(f"AI API kutilmagan javob: {str(data)[:200]}") from e
    if not isinstance(message, dict):
        raise AIError(f"AI API kutilmagan javob: {str(data)[:200]}")
    return message


async def ask_ai(messages: list[dict[str, str]], *, max_tokens: int | None = None, attempts: int | None = None) -> str:
    """OpenAI formatidagi chat/completions so'rovi; javob matnini qaytaradi (attempts: urinishlar soni, standart ATTEMPTS)."""
    data = await _post({"messages": messages, "max_tokens": max_tokens or MAX_TOKENS}, attempts)
    text = (_message(data).get("content") or "").strip()
    if not text:
        raise AIError("AI API bo'sh javob qaytardi")
    return text


async def ask_ai_tools(
    messages: list[dict[str, str]],
    tools: list[dict],
    *,
    tool_choice: dict | None = None,
    max_tokens: int | None = None,
) -> tuple[str, list[tuple[str, dict]]]:
    """Tool calling: (javob matni, [(tool nomi, argumentlar), ...]); matn ham, tool ham bo'lmasa AIError."""
    payload = {"messages": messages, "tools": tools, "max_tokens": max_tokens or MAX_TOKENS}
    if tool_choice:
        payload["tool_choice"] = tool_choice
    message = _message(await _post(payload))

    calls: list[tuple[str, dict]] = []
    for call in message.get("tool_calls") or []:
        function = call.get("function") if isinstance(call, dict) else None
        if not isinstance(function, dict) or not function.get("name"):
            continue
        args = function.get("arguments")
        if isinstance(args, str):
            try:
                args = json.loads(args) if args.strip() else {}
            except ValueError:
                args = {}
        calls.append((function["name"], args if isinstance(args, dict) else {}))

    text = (message.get("content") or "").strip()
    # tool'lar berilgan, lekin AI chaqirmadimi, yoki API `tools` ni umuman qo'llamadimi: shu qator ko'rsatadi
    logger.info(
        "AI tool calling: yuborilgan tool'lar=%s, chaqirilgan=%s, matn=%s belgi",
        [t["function"]["name"] for t in tools], [n for n, _ in calls], len(text),
    )
    if not text and not calls:
        raise AIError("AI API bo'sh javob qaytardi")
    return text, calls
