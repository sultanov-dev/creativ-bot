from html import escape


def welcome_text(full_name: str) -> str:
    return (
        f"Assalomu alaykum, <b>{escape(full_name)}</b>! 👋\n"
        "Dasturchilar choyxonasiga xush kelibsiz, sizni ko'rganimizdan xursandmiz! 😊\n\n"
        "Guruhga qo'shilishdan oldin sizni yaqinroq tanishtirishingizni iltimos qilamiz. "
        "Bir nechta savolga javob bersangiz bo'ldi, bu atigi bir necha daqiqa vaqtingizni oladi. "
        "Vaqt ajratganingiz uchun oldindan rahmat! 🙏"
    )
