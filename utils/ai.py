import asyncio
import json
import logging
import re
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


TOOL_PROTOCOL = (
    "Respond with ONE JSON object and nothing else (no Markdown, no code fence): "
    '{{"reply": "<text for the user, or an empty string>", "tool": "<tool name, or null>", "arguments": {{...}}}}. '
    "Use \"tool\" only when a tool below must be called, otherwise set it to null. Escape double quotes inside strings. "
    "Available tools:\n{tools}"
)
_PARTIAL_REPLY = re.compile(r'"reply"\s*:\s*"((?:[^"\\]|\\.)*)')


def _tools_text(tools: list[dict]) -> str:
    lines = []
    for tool in tools:
        function = tool["function"]
        params = json.dumps(function.get("parameters", {}), ensure_ascii=False)
        lines.append(f"- {function['name']}: {function['description']} Arguments (JSON schema): {params}")
    return "\n".join(lines)


def _parse_tool_reply(content: str, names: set[str]) -> tuple[str, list[tuple[str, dict]]]:
    """JSON protokoldagi javobni (matn, [(tool, argumentlar)]) ga ajratadi; JSON bo'lmasa, butun matn javob hisoblanadi."""
    start = content.find("{")
    data = None
    if start != -1:
        try:
            data, _ = json.JSONDecoder().raw_decode(content[start:])
        except ValueError:
            data = None
    if not isinstance(data, dict):
        partial = _PARTIAL_REPLY.search(content) if content.lstrip().startswith(("{", "`")) else None
        if partial:  # JSON uzilib qolgan (max_tokens): hech bo'lmasa reply qismini olamiz
            try:
                return json.loads(f'"{partial.group(1)}"').strip(), []
            except ValueError:
                pass
        return content.strip(), []

    reply = data.get("reply")
    text = reply.strip() if isinstance(reply, str) else ""
    name = data.get("tool")
    args = data.get("arguments")
    calls = [(name, args if isinstance(args, dict) else {})] if isinstance(name, str) and name in names else []
    return text, calls


async def ask_ai_tools(
    messages: list[dict[str, str]],
    tools: list[dict],
    *,
    max_tokens: int | None = None,
) -> tuple[str, list[tuple[str, dict]]]:
    """Tool calling JSON protokol orqali: (javob matni, [(tool nomi, argumentlar), ...]).

    API'ning `tools` parametri ishlatilmaydi (gateway unda 503 qaytaradi): tool'lar tizim ko'rsatmasida
    tasvirlanadi va AI JSON obyekt bilan javob beradi. Matn ham, tool ham bo'lmasa AIError.
    """
    protocol = {"role": "system", "content": TOOL_PROTOCOL.format(tools=_tools_text(tools))}
    data = await _post({"messages": [*messages, protocol], "max_tokens": max_tokens or MAX_TOKENS})
    content = (_message(data).get("content") or "").strip()
    text, calls = _parse_tool_reply(content, {t["function"]["name"] for t in tools})
    # tool'lar berilgan, lekin AI chaqirmadimi: shu qator ko'rsatadi
    logger.info(
        "AI tool calling: tool'lar=%s, chaqirilgan=%s, matn=%s belgi",
        [t["function"]["name"] for t in tools], [n for n, _ in calls], len(text),
    )
    if not text and not calls:
        raise AIError("AI API bo'sh javob qaytardi")
    return text, calls
