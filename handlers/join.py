import logging

from aiogram import Bot, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import ChatJoinRequest

from database import get_active_application, get_profile, last_application_status
from handlers.profile import show_review
from states import Form
from texts import ALREADY_APPLIED, REJOIN_AFTER_REJECTION
from utils.admin import safe_send
from utils.fsm import get_private_state
from utils.get_welcome import welcome_text
from utils.questions import ask

router = Router()
logger = logging.getLogger(__name__)


@router.chat_join_request()
async def join_request(request: ChatJoinRequest, bot: Bot, state: FSMContext):
    # avvalgi ariza hali ko'rib chiqilayotgan bo'lsa, anketani qayta to'ldirtirmaymiz
    if await get_active_application(request.from_user.id, request.chat.id):
        await safe_send(
            bot=bot, chat_id=request.user_chat_id, text=ALREADY_APPLIED
        )
        return

    private_state = get_private_state(
        storage=state.storage, bot=bot, user_id=request.from_user.id
    )

    # avvalgi ariza rad etilgan bo'lsa: eski ma'lumotlar ko'rsatilmaydi va qayta ishlatilmaydi, anketa yangidan
    rejected_before = await last_application_status(request.from_user.id, request.chat.id) == "rejected"

    # avval anketa to'ldirgan (va rad etilmagan) bo'lsa: ma'lumotlarni ko'rsatamiz, o'zgartirish yoki shunday qoldirishni so'raymiz
    profile = None if rejected_before else await get_profile(request.from_user.id)
    if profile:
        await private_state.set_data(
            {
                **profile,
                # username so'ralmaydi: Telegram'dan olinadi (anketada ko'rinmaydi, faqat bazada saqlanadi)
                "username": request.from_user.username,
                "group_id": request.chat.id,
                "user_id": request.user_chat_id,
            }
        )
        await private_state.set_state(Form.review)
        await show_review(bot, request.user_chat_id, private_state)
        return

    # holat javob kelishidan oldin o'rnatilishi kerak
    await private_state.set_state(Form.full_name)
    await private_state.set_data(
        {
            "group_id": request.chat.id,
            "user_id": request.user_chat_id,
            "username": request.from_user.username,  # so'ralmaydi, Telegram'dan olinadi
        }
    )

    await bot.send_message(
        chat_id=request.user_chat_id,
        text=REJOIN_AFTER_REJECTION if rejected_before else welcome_text(),
    )
    await ask(bot, request.user_chat_id, Form.full_name, delay=0.6)
