from html import escape

# anketaning foydalanuvchiga tegishli maydonlari (database.profiles'da saqlanadi)
PROFILE_FIELDS = (
    "full_name", "username", "phone", "age", "job", "about", "join_group",
)


def full_name_of(data: dict) -> str:
    """To'liq ism. Eski saqlangan anketalarda ism va familiya alohida (first_name/last_name) bo'ladi."""
    if data.get("full_name"):
        return data["full_name"]
    return " ".join(p for p in (data.get("first_name"), data.get("last_name")) if p)


def format_anketa(data: dict, *, with_phone: bool = False) -> str:
    """Anketa matni. Telefon shaxsiy ma'lumot: guruhga ketadigan variantda with_phone=False."""
    lines = [f"👤 <b>Ism:</b> {escape(full_name_of(data))}"]
    if data.get("username"):
        lines.append(f"🔗 <b>Username:</b> @{escape(data['username'])}")
    if with_phone and data.get("phone"):
        lines.append(f"📞 <b>Telefon:</b> {escape(data['phone'])}")
    lines += [
        f"🎂 <b>Yosh:</b> {data.get('age')}",
        f"💼 <b>Kasb:</b> {escape(data['job'])}",
        f"📝 <b>O'zi haqida:</b> {escape(data['about'])}",
        f"❓ <b>Qo'shilish sababi:</b> {escape(data['join_group'])}",
    ]
    return "\n".join(lines) + "\n"
