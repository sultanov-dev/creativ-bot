"""Lichkadagi suhbatda AI masalani qaysi turga ajratishi va har bir turga qaror (handlers/support.py)."""
import re


# adminga uzatiladigan masala turlari (escalate_to_admin tool'ining category qiymatlari)
FORWARD_CATEGORIES = (
    "complaint",  # a'zo yoki admin ustidan shikoyat
    "payment",  # to'lov, pul muammosi
    "safety",  # tahdid, xavfsizlik
    "appeal",  # ban yoki kirish bo'yicha e'tiroz
    "data_removal",  # shaxsiy ma'lumotni o'chirish so'rovi
    "suggestion",  # taklif, fikr-mulohaza
    "allowed_ad",  # ruxsat etilgan reklama
    "other",  # boshqa haq masala
)

# adminga yetkazilmaydigan masala turlari (decline tool'ining category qiymatlari)
DECLINE_CATEGORIES = (
    "prohibited_ad",  # taqiqlangan reklama
    "abuse",  # haqorat, qo'pol so'zlar
    "indecent",  # nomaqul (axloqsiz) takliflar
    "scam",  # firibgarlik
    "spam",
    "no_purpose",  # admin kerak, lekin nima uchunligini aytmadi
    "unclear",  # aniqlashtirishdan keyin ham noaniq
)

# musiqa va konsert reklamasi taqiqlanmagan; qolgani ro'yxatdagilar
PROHIBITED_ADS = (
    "gambling, betting, casino, lottery",
    "alcohol, drugs",
    "usury: loans or credit with interest, microloans with interest",
    "adult (18+) content, dating or immoral services",
    "pork and other forbidden food",
    "fortune telling, magic, astrology",
    "fraud: pyramids, get rich quick schemes, fake documents",
    "weapons, smuggling",
    "tobacco and vape",
    "cryptocurrency and forex trading",
    "insurance",
)

# bir foydalanuvchining adminga uzatishlari: kuniga ko'pi bilan shuncha
MAX_ESCALATIONS_PER_DAY = 3
# rad etilgan foydalanuvchi shuncha soat ichida qayta urinsa, AI'siz qisqa rad javobi oladi, lekin faqat quyidagi
# sabablar bilan yopilgan bo'lsa: haqorat va kunlik limit. Boshqa rad etishlar (masalan, taqiqlangan reklama,
# noaniq masala) foydalanuvchini to'smaydi: u yangi suhbat ochib, masalasini qayta tushuntira oladi
DECLINE_COOLDOWN_HOURS = 24
BLOCKING_CATEGORIES = ("abuse", "violation", "limit")  # violation: xavfli havola yoki 18+ kontent takrorlandi

# lichkada AI suhbat faqat shu mazmundagi xabar bilan ochiladi (AI'siz, mahalliy): admin/moderator/guruh egasi bilan
# gaplashish, shikoyat, ban/blok bo'yicha murojaat. Boshqa xabarga AI chaqirilmaydi, qisqa yo'l-yo'riq beriladi
ADMIN_INTENT_RE = re.compile(
    r"\b(?:admin|админ|administrator|администратор|moder|модер|owner|владел|создател|egas[iy]|эгас[и]|"
    r"yaratuvchi|яратувчи|shikoyat|шикоят|жалоб|complain|report|репорт|murojaat|мурожаат|обращени|support|"
    r"поддержк|разбан|забан|заблок|разблок|unban|ban(?:\b|ga\b|dan\b|ni\b|ned\b|la\w*)|бан(?:\b|а\b|ом\b|ил\w*|ят\w*)|"
    r"blok(?:\b|la\w*|dan\b|ga\b)|блок(?:\b|ир\w*|ла\w*|дан\b))",
    re.IGNORECASE,
)


def wants_admin(text: str) -> bool:
    """Foydalanuvchi admin bilan bog'lanmoqchimi (kalit so'zlar, AI'siz)."""
    return bool(ADMIN_INTENT_RE.search(text or ""))
