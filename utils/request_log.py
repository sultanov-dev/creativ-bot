import logging
import time
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware, Bot
from aiogram.client.session.middlewares.base import (
    BaseRequestMiddleware,
    NextRequestMiddlewareType,
)
from aiogram.dispatcher.event.bases import UNHANDLED
from aiogram.methods import TelegramMethod
from aiogram.types import TelegramObject, Update

incoming = logging.getLogger("tg.in")
outgoing = logging.getLogger("tg.out")

# polling har soniyada chaqiriladi: faqat DEBUG da ko'rinadi
NOISY_METHODS = {"GetUpdates"}


def _short(text: str | None, limit: int = 80) -> str:
    text = (text or "").replace("\n", " ")
    return text if len(text) <= limit else text[:limit] + "…"


def _describe_update(update: Update) -> str:
    event = update.event
    user = getattr(event, "from_user", None)
    chat = getattr(event, "chat", None) or getattr(
        getattr(event, "message", None), "chat", None
    )
    parts = [f"update={update.update_id}", f"type={update.event_type}"]
    if user:
        parts.append(f"user={user.id}" + (f"(@{user.username})" if user.username else ""))
    if chat:
        parts.append(f"chat={chat.id}({chat.type})")

    text = getattr(event, "text", None)
    if text:
        # anketa javoblari shaxsiy ma'lumot: faqat buyruq matni, qolganlari uzunligi bilan
        parts.append(f"text={_short(text, 50)!r}" if text.startswith("/") else f"text(len={len(text)})")
    data = getattr(event, "data", None)
    if isinstance(data, str):
        parts.append(f"data={data!r}")
    return " ".join(parts)


class UpdateLogMiddleware(BaseMiddleware):
    """Kelayotgan har bir update: kim, qayerdan, nima; qancha vaqtda va ishlanganmi."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        description = _describe_update(event) if isinstance(event, Update) else str(event)
        incoming.info("← %s", description)
        started = time.monotonic()
        try:
            result = await handler(event, data)
        except Exception:
            incoming.exception("✗ handler xatosi (%s)", description)
            raise
        ms = (time.monotonic() - started) * 1000
        state = "e'tiborsiz (handler topilmadi)" if result is UNHANDLED else "ishlandi"
        incoming.info("✓ %s, %.0f ms", state, ms)
        return result


def _describe_method(method: TelegramMethod) -> str:
    parts = []
    for name in ("chat_id", "user_id", "message_id", "callback_query_id"):
        value = getattr(method, name, None)
        if value is not None:
            parts.append(f"{name}={value}")
    text = getattr(method, "text", None) or getattr(method, "caption", None)
    if text:
        parts.append(f"text(len={len(text)})={_short(text, 40)!r}")
    if getattr(method, "reply_markup", None):
        parts.append("reply_markup")
    return " ".join(parts)


class RequestLogMiddleware(BaseRequestMiddleware):
    """Telegram'ga ketayotgan har bir so'rov va javob: metod, asosiy parametrlar, natija, vaqt."""

    async def __call__(
        self,
        make_request: NextRequestMiddlewareType,
        bot: Bot,
        method: TelegramMethod,
    ) -> Any:
        name = type(method).__name__
        noisy = name in NOISY_METHODS
        level = logging.DEBUG if noisy else logging.INFO
        description = _describe_method(method)
        outgoing.log(level, "→ %s %s", name, description)

        started = time.monotonic()
        try:
            response = await make_request(bot, method)
        except Exception as exc:
            ms = (time.monotonic() - started) * 1000
            outgoing.warning("✗ %s %s: %s: %s, %.0f ms", name, description, type(exc).__name__, exc, ms)
            raise

        ms = (time.monotonic() - started) * 1000
        outgoing.log(level, "✓ %s %s, %.0f ms", name, type(response).__name__, ms)
        return response
