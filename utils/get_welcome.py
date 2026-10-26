from html import escape


def welcome_text(full_name: str) -> str:
    return (
        f"Assalomu alaykum, <b>{escape(full_name)}</b>! 👋\n"
        "Dasturchilar choyxonasiga xush kelibsiz.\n"
        "Qo'shilishdan oldin bir nechta savolga javob berasiz."
    )
