"""👎 sabablarini tekshirish: faqat kod (utils/profanity), AI'siz va darhol."""
import logging

from utils.profanity import has_profanity

logger = logging.getLogger(__name__)


async def is_abusive(text: str) -> bool:
    """So'kinish yoki odobsiz so'z bo'lsa True (mahalliy filtr: o'zbek, rus, ingliz; kirill, maska, harflab yozilgan)."""
    text = (text or "").strip()
    if text and has_profanity(text):
        logger.info("Moderatsiya: matn rad etildi (uzunligi %s)", len(text))
        return True
    return False
