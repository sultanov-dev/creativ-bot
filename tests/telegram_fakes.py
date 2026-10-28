"""Telegram'siz sinash uchun: soxta sessiya (barcha so'rovlar yozib olinadi) va Update yasovchilar."""
import itertools
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, TypeVar

from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramNetworkError, TelegramRetryAfter
from aiogram.methods import (
    GetChat,
    GetChatAdministrators,
    GetChatMember,
    GetChatMemberCount,
    GetMe,
    SendMessage,
    TelegramMethod,
)
from aiogram.types import (
    CallbackQuery,
    Chat,
    ChatJoinRequest,
    ChatMemberAdministrator,
    ChatMemberBanned,
    ChatMemberLeft,
    ChatMemberMember,
    ChatMemberOwner,
    ChatMemberRestricted,
    ChatPermissions,
    Contact,
    Message,
    MessageEntity,
    Update,
    User,
)

BOT_ID = 123456
BOT_USERNAME = "choyxona_bot"
GROUP_ID = -1001234567890
ADMIN_ID = 1001
ADMIN2_ID = 1002
DEVELOPER_ID = 9001

M = TypeVar("M", bound=TelegramMethod)


def bad_request(msg: str = "Bad Request: x", method: TelegramMethod | None = None) -> TelegramBadRequest:
    return TelegramBadRequest(method=method or GetMe(), message=msg)


def forbidden(method: TelegramMethod | None = None) -> TelegramForbiddenError:
    return TelegramForbiddenError(method=method or GetMe(), message="Forbidden: bot was blocked by the user")


def retry_after(method: TelegramMethod | None = None) -> TelegramRetryAfter:
    return TelegramRetryAfter(method=method or GetMe(), message="Flood", retry_after=1)


def network_error(method: TelegramMethod | None = None) -> TelegramNetworkError:
    return TelegramNetworkError(method=method or GetMe(), message="boom")


def now() -> datetime:
    return datetime.now(timezone.utc)


def make_user(user_id: int, first_name: str = "Test", *, is_bot: bool = False, username: str | None = None,
              last_name: str | None = None) -> User:
    return User(id=user_id, is_bot=is_bot, first_name=first_name, last_name=last_name, username=username)


class FakeSession(BaseSession):
    """Bot API o'rniga: har bir so'rovni `requests` ro'yxatiga yozadi va mantiqiy javob qaytaradi.

    - `statuses[(chat_id, user_id)]`: get_chat_member javobi ('member', 'left', 'administrator', ...)
    - `names[user_id]`: get_chat_member qaytaradigan first_name ("Deleted Account" sinovi uchun)
    - `errors[MethodClass]`: Exception yoki chaqiriladigan funksiya (method -> Exception | None)
    """

    def __init__(self) -> None:
        super().__init__()
        self.requests: list[TelegramMethod] = []
        self.statuses: dict[tuple[int, int], str] = {}
        self.default_status = "member"
        self.names: dict[int, str] = {}
        self.errors: dict[type, Any] = {}
        self.member_count = 42
        self.group_admins: dict[int, list[int]] = {}  # chat_id -> Telegram guruh adminlari (GetChatMember ham shuni qaytaradi)
        self._ids = itertools.count(1000)

    async def close(self) -> None:  # pragma: no cover
        pass

    async def stream_content(self, *a: Any, **kw: Any) -> AsyncGenerator[bytes, None]:  # pragma: no cover
        raise NotImplementedError
        yield b""

    def of(self, method_type: type[M]) -> list[M]:
        return [m for m in self.requests if isinstance(m, method_type)]

    def sent_to(self, chat_id: int) -> list[SendMessage]:
        return [m for m in self.of(SendMessage) if m.chat_id == chat_id]

    def texts_to(self, chat_id: int) -> list[str]:
        return [m.text for m in self.sent_to(chat_id)]

    def clear(self) -> None:
        self.requests.clear()

    async def make_request(self, bot: Bot, method: TelegramMethod[Any], timeout: int | None = None) -> Any:
        self.requests.append(method)
        err = self.errors.get(type(method))
        if callable(err) and not isinstance(err, BaseException):
            err = err(method)
        if isinstance(err, BaseException):
            raise err
        result = self._result(method)
        # haqiqiy Response natijani bot kontekstida yaratadi: message.edit_text() kabilar ishlashi uchun
        return result.as_(bot) if hasattr(result, "as_") else result

    def _chat(self, chat_id: int) -> Chat:
        return Chat(id=chat_id, type="private" if chat_id > 0 else "supergroup", title=None if chat_id > 0 else "G")

    def _result(self, method: TelegramMethod[Any]) -> Any:
        if isinstance(method, SendMessage):
            return Message(
                message_id=next(self._ids),
                date=now(),
                chat=self._chat(int(method.chat_id)),
                from_user=make_user(BOT_ID, "Bot", is_bot=True, username=BOT_USERNAME),
                text=method.text,
            )
        if isinstance(method, GetMe):
            return make_user(BOT_ID, "Bot", is_bot=True, username=BOT_USERNAME)
        if isinstance(method, GetChatMember):
            default = "administrator" if method.user_id in self.group_admins.get(int(method.chat_id), []) else self.default_status
            status = self.statuses.get((int(method.chat_id), method.user_id), default)
            user = make_user(method.user_id, self.names.get(method.user_id, f"U{method.user_id}"))
            if status == "left":
                return ChatMemberLeft(status=ChatMemberStatus.LEFT, user=user)
            if status == "kicked":
                return ChatMemberBanned(status=ChatMemberStatus.KICKED, user=user, until_date=now())
            if status == "administrator":
                return ChatMemberAdministrator(
                    status=ChatMemberStatus.ADMINISTRATOR, user=user, can_be_edited=False, is_anonymous=False,
                    can_manage_chat=True, can_delete_messages=True, can_manage_video_chats=True,
                    can_restrict_members=True, can_promote_members=False, can_change_info=True,
                    can_invite_users=True, can_post_stories=False, can_edit_stories=False,
                    can_delete_stories=False, can_send_welcome_messages=False,
                )
            if status == "creator":
                return ChatMemberOwner(status=ChatMemberStatus.CREATOR, user=user, is_anonymous=False)
            if status in ("restricted", "restricted_out"):
                return ChatMemberRestricted(
                    status=ChatMemberStatus.RESTRICTED, user=user, is_member=status == "restricted",
                    can_send_messages=False, can_send_audios=False, can_send_documents=False,
                    can_send_photos=False, can_send_videos=False, can_send_video_notes=False,
                    can_send_voice_notes=False, can_send_polls=False, can_send_other_messages=False,
                    can_add_web_page_previews=False, can_react_to_messages=False, can_edit_tag=False,
                    can_change_info=False, can_invite_users=False,
                    can_pin_messages=False, can_manage_topics=False, until_date=now(),
                )
            return ChatMemberMember(status=ChatMemberStatus.MEMBER, user=user)
        if isinstance(method, GetChatAdministrators):
            chat = int(method.chat_id)
            ids = list(self.group_admins.get(chat, []))
            ids += [u for (c, u), st in self.statuses.items() if c == chat and st in ("administrator", "creator") and u not in ids]
            members = [self._result(GetChatMember(chat_id=chat, user_id=u)) for u in ids]
            # haqiqiy Telegram botning o'zini ham qaytaradi: u anketa oluvchilar qatoriga kirmasligi kerak
            members.append(ChatMemberAdministrator(
                status=ChatMemberStatus.ADMINISTRATOR, user=make_user(BOT_ID, "Bot", is_bot=True, username=BOT_USERNAME),
                can_be_edited=False, is_anonymous=False, can_manage_chat=True, can_delete_messages=True,
                can_manage_video_chats=True, can_restrict_members=True, can_promote_members=False, can_change_info=True,
                can_invite_users=True, can_post_stories=False, can_edit_stories=False, can_delete_stories=False,
                can_send_welcome_messages=False,
            ))
            return members
        if isinstance(method, GetChatMemberCount):
            return self.member_count
        if isinstance(method, GetChat):
            return _full_chat(int(method.chat_id), getattr(self, "linked_chats", {}).get(int(method.chat_id)))
        # qolgan barcha metodlar (answer_callback_query, ban, delete, edit...) uchun oddiy muvaffaqiyat
        return True
        return True


def _full_chat(chat_id: int, linked_chat_id: int | None = None):
    from aiogram.types import AcceptedGiftTypes, ChatFullInfo

    return ChatFullInfo(
        id=chat_id, type="supergroup", title="G", accent_color_id=0, max_reaction_count=0,
        accepted_gift_types=AcceptedGiftTypes(
            unlimited_gifts=False, limited_gifts=False, unique_gifts=False, premium_subscription=False, gifts_from_channels=False
        ),
        permissions=ChatPermissions(can_send_messages=True),
        linked_chat_id=linked_chat_id,
    )


def make_bot(session: FakeSession | None = None) -> Bot:
    return Bot(token=f"{BOT_ID}:TESTTOKEN", session=session or FakeSession())


_update_ids = itertools.count(1)


def private_message(user_id: int, text: str | None = None, *, contact: Contact | None = None,
                    chat_id: int | None = None, message_id: int | None = None) -> Update:
    chat_id = user_id if chat_id is None else chat_id
    return Update(
        update_id=next(_update_ids),
        message=Message(
            message_id=message_id or next(_update_ids) + 5000,
            date=now(),
            chat=Chat(id=chat_id, type="private"),
            from_user=make_user(user_id, f"U{user_id}", username=f"user{user_id}"),
            text=text,
            contact=contact,
        ),
    )


def group_message(user_id: int, text: str, *, chat_id: int = GROUP_ID, reply_to: Message | None = None,
                  entities: list[MessageEntity] | None = None, message_id: int | None = None,
                  first_name: str | None = None) -> Update:
    return Update(
        update_id=next(_update_ids),
        message=group_message_obj(user_id, text, chat_id=chat_id, reply_to=reply_to, entities=entities,
                                  message_id=message_id, first_name=first_name),
    )


def group_message_obj(user_id: int, text: str, *, chat_id: int = GROUP_ID, reply_to: Message | None = None,
                      entities: list[MessageEntity] | None = None, message_id: int | None = None,
                      first_name: str | None = None) -> Message:
    return Message(
        message_id=message_id or next(_update_ids) + 9000,
        date=now(),
        chat=Chat(id=chat_id, type="supergroup", title="G"),
        from_user=make_user(user_id, first_name or f"U{user_id}"),
        text=text,
        reply_to_message=reply_to,
        entities=entities,
    )


def mention(text: str, username: str = BOT_USERNAME) -> MessageEntity:
    start = text.lower().index(f"@{username.lower()}")
    return MessageEntity(type="mention", offset=start, length=len(username) + 1)


def callback(user_id: int, data: str, *, chat_id: int | None = None, message_id: int = 777,
             message_text: str = "anketa") -> Update:
    chat_id = user_id if chat_id is None else chat_id
    return Update(
        update_id=next(_update_ids),
        callback_query=CallbackQuery(
            id=f"cb{next(_update_ids)}",
            from_user=make_user(user_id, f"U{user_id}"),
            chat_instance="ci",
            data=data,
            message=Message(
                message_id=message_id,
                date=now(),
                chat=Chat(id=chat_id, type="private" if chat_id > 0 else "supergroup"),
                text=message_text,
            ),
        ),
    )


def join_request(user_id: int, chat_id: int = GROUP_ID) -> Update:
    return Update(
        update_id=next(_update_ids),
        chat_join_request=ChatJoinRequest(
            chat=Chat(id=chat_id, type="supergroup", title="G"),
            from_user=make_user(user_id, f"U{user_id}", username=f"user{user_id}"),
            user_chat_id=user_id,
            date=now(),
        ),
    )
