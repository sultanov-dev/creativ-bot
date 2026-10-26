from html import escape


def welcome_text(full_name: str) -> str:
    return (
        f"Assalomu alaykum, <b>{escape(full_name)}</b>! 👋\n"
        "Dasturchilar choyxonasiga xush kelibsiz! 😊\n\n"
        "Qo'shilishdan oldin bir nechta savolga javob bersangiz, juda xursand bo'lamiz. "
        "Bu bir necha daqiqa vaqtingizni oladi. Rahmat! 🙏"
    )
