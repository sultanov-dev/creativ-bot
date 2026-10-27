import logging

from aiogram import Bot, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import ChatJoinRequest

from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramForbiddenError

from config import REJOIN_COOLDOWN_SECONDS
from database import get_active_application, get_profile, last_application_status, rejoin_wait_seconds
from handlers.profile import show_review
from states import Form
from texts import ALREADY_APPLIED, FINISH_FORM_FIRST, REJOIN_COOLDOWN, REJOIN_NOTES
from utils.admin import safe_send
from utils.fsm import get_private_state
from utils.get_welcome import welcome_text
from utils.questions import ask
from utils.timefmt import format_wait

router = Router()

REVIEW_STATES = (Form.review.state, Form.pick_field.state)
FORM_STATES = (
    Form.full_name.state, Form.phone.state, Form.age.state, Form.job.state, Form.about.state,
    Form.join_group.state, *REVIEW_STATES,
)
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

    # anketa hali tugamagan (ariza yaratilmagan): yangi so'rov uni boshidan boshlamaydi, davom ettirishni aytamiz
    current = await private_state.get_state()
    if current in FORM_STATES and (await private_state.get_data()).get("group_id") == request.chat.id:
        try:
            await bot.send_message(chat_id=request.user_chat_id, text=FINISH_FORM_FIRST)
            if current in REVIEW_STATES:
                await show_review(bot, request.user_chat_id, private_state)
            else:
                await ask(bot, request.user_chat_id, current, delay=0.3)
        except (TelegramForbiddenError, TelegramBadRequest):
            await _abort(bot, request, private_state)
        return

    # rad etilgandan keyin darhol qayta ariza berib, adminlarni charchatmaslik uchun qisqa kutish
    wait = await rejoin_wait_seconds(request.from_user.id, request.chat.id, REJOIN_COOLDOWN_SECONDS)
    if wait:
        try:
            # kutilayotgan so'rov qolsa, foydalanuvchi keyin yangisini yubora olmaydi
            await bot.decline_chat_join_request(chat_id=request.chat.id, user_id=request.from_user.id)
        except TelegramAPIError:
            pass
        await safe_send(bot=bot, chat_id=request.user_chat_id, text=REJOIN_COOLDOWN.format(wait=format_wait(wait)))
        return

    # oxirgi ariza rad etilgan, muddati o'tgan yoki ko'rib chiqilmagan (failed) bo'lsa: eski ma'lumotlar
    # ko'rsatilmaydi va qayta ishlatilmaydi, anketa yangidan, sababi haqida qisqa xabar bilan
    fresh_note = REJOIN_NOTES.get(await last_application_status(request.from_user.id, request.chat.id))

    # aks holda avval anketa to'ldirgan bo'lsa: ma'lumotlarni ko'rsatamiz, o'zgartirish yoki shunday qoldirishni so'raymiz
    profile = None if fresh_note else await get_profile(request.from_user.id)
    try:
        await _begin(bot, request, private_state, profile, fresh_note)
    except (TelegramForbiddenError, TelegramBadRequest):
        await _abort(bot, request, private_state)


async def _abort(bot: Bot, request: ChatJoinRequest, private_state: FSMContext) -> None:
    """Foydalanuvchiga yozib bo'lmadi (masalan, bot uzoq o'chiq turgani uchun so'rovdan keyingi ~5 daqiqalik oyna
    yopilgan): holat tozalanadi va so'rov rad etiladi, shunda foydalanuvchi uni qayta yuborib, yangi oyna ochadi."""
    logger.warning("Foydalanuvchi %s ga anketa boshlanishini yozib bo'lmadi: so'rov rad etildi", request.from_user.id)
    await private_state.clear()
    try:
        await bot.decline_chat_join_request(chat_id=request.chat.id, user_id=request.from_user.id)
    except TelegramAPIError:
        pass


async def _begin(bot: Bot, request: ChatJoinRequest, private_state: FSMContext, profile, fresh_note) -> None:
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
        text=fresh_note or welcome_text(),
    )
    await ask(bot, request.user_chat_id, Form.full_name, delay=0.6)
