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
BLOCKING_CATEGORIES = (
    "abuse",
    "violation",
    "limit",
)  # violation: xavfli havola yoki 18+ kontent takrorlandi

# Lichkada AI suhbat faqat "admin kerak" mazmunidagi xabar bilan ochiladi. Faqat kod (AI'siz, darhol):
# 1) aniq so'zlar (admin, moderator, guruh egasi, shikoyat, ban...);
# 2) mas'ul shaxs so'ralgan (mas'ul, rahbar, operator, tirik odam, человек, someone in charge...);
# 3) guruhdan chiqarilgani / xabari o'chirilgani haqida shikoyat ("guruhdan chiqarib yuborishdi", "меня удалили");
# 4) bog'lanish istagi + guruh mavzusi ("guruh bo'yicha kim bilan bog'lansam", "меня удалили из группы, с кем связаться").
# "yordam", "muammo", "guruh" kabi umumiy so'zlarning o'zi yetmaydi: oddiy savol suhbat ochmasin.
ADMIN_INTENT_RE = re.compile(
    r"\b(?:adm[iy]?n|адм[иі]н|амдин|administrator|администратор|moder|модер|owner|владел|создател|egas[iy]|эгас[и]|"
    r"yaratuvchi|яратувчи|shikoyat|шикоят|жалоб|complain|report|репорт|murojaat|мурожаат|обращени|support|"
    r"поддержк|разбан|забан|заблок|разблок|unban|ban(?:\b|ga\b|dan\b|ni\b|ned\b|la\w*)|бан(?:\b|а\b|ом\b|ил\w*|ят\w*)|"
    r"blok(?:\b|la\w*|dan\b|ga\b)|блок(?:\b|ир\w*|ла\w*|дан\b))",
    re.IGNORECASE,
)
PERSON_RE = re.compile(
    r"\b(?:mas.?ul|масъул|масул|rahbar|раҳбар|рахбар|boshliq|бошлиқ|javobgar|жавобгар|operator|оператор|"
    r"(?:tirik|jonli|haqiqiy)\s+(?:odam|inson)|(?:odam|inson|kimdir)\s+bilan|(?:одам|инсон)\s+билан|"
    r"человек|руковод|ответствен|главн\w*\s+(?:в|по|групп)|"
    r"human|real person|someone in charge|person in charge|manager)",
    re.IGNORECASE,
)
REMOVED_RE = re.compile(
    r"\b(?:chiqarib\s+yubor|chetlat|o.?chirib\s+(?:yubor|tashla)(?:ishdi|ishgan|i?bdi(?:lar)?)|ўчириб\s+(?:юбор|ташла)(?:ишди|ишган|и?бди)|удалил|выгнал|кикнул|"
    r"исключил|kicked|removed me|banned me)",
    re.IGNORECASE,
)
CONTACT_RE = re.compile(
    r"\b(?:bog.?lan|боғлан|боглан|aloqa|алоқа|gaplash|гаплаш|связ|поговор|contact|talk|speak)", re.IGNORECASE
)
TOPIC_RE = re.compile(
    r"\b(?:guruh|гуруҳ|гурух|chiqarib|chetlat|o.?chirib|ўчириб|qoida|қоида|групп|удалил|выгнал|кикнул|правил|"
    r"group|kicked|removed|rules)",
    re.IGNORECASE,
)


def wants_admin(text: str) -> bool:
    """Aniq "admin kerak" (kalit so'zlar, AI'siz)."""
    return bool(ADMIN_INTENT_RE.search(text or ""))


def wants_person(text: str) -> bool:
    """Admin so'zisiz, lekin mas'ul shaxs yoki guruh bo'yicha bog'lanish so'ralgan (AI'siz)."""
    text = text or ""
    return bool(
        PERSON_RE.search(text) or REMOVED_RE.search(text) or (CONTACT_RE.search(text) and TOPIC_RE.search(text))
    )
