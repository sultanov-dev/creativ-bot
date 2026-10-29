"""Lichkadagi xabar admin bilan bog'lanish so'rovimi: faqat kod (utils/support_policy), AI'siz va darhol.
Boshqa xabarlar e'tiborsiz qoladi (bot tez, AI so'rovi yo'q)."""
from utils.support_policy import wants_admin, wants_person


async def asks_for_admin(text: str) -> bool:
    """True: admin yoki mas'ul shaxs bilan bog'lanmoqchi (aniq so'z yoki mas'ul shaxs / guruh bo'yicha bog'lanish)."""
    text = (text or "").strip()
    return bool(text) and (wants_admin(text) or wants_person(text))
