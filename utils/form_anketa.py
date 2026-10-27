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
    if with_phone and data.get("phone"):
        lines.append(f"📞 <b>Telefon:</b> {escape(data['phone'])}")
    lines += [
        f"🎂 <b>Yosh:</b> {data.get('age')}",
        f"💼 <b>Kasb:</b> {escape(data['job'])}",
        f"📝 <b>O'zi haqida:</b> {escape(data['about'])}",
        f"❓ <b>Qo'shilish sababi:</b> {escape(data['join_group'])}",
    ]
    return "\n".join(lines) + "\n"


def anketa_for_admins(anketa: str, phone: str | None) -> str:
    """Saqlangan (telefonsiz) anketa matniga telefon qatorini format_anketa(with_phone=True) dagi joyiga qo'yadi."""
    if not phone:
        return anketa
    first, _, rest = anketa.partition("\n")
    return f"{first}\n📞 <b>Telefon:</b> {escape(phone)}\n{rest}"
