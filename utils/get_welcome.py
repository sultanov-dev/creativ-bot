from html import escape


def welcome_text(full_name: str) -> str:
    return (
        f"Assalomu alaykum, {escape(full_name)}! 👋\n"
        "Dasturchilar choyxonasiga xush kelibsiz.\n"
        "Qo'shilishdan oldin bir nechta savolga javob berasiz."
    )
