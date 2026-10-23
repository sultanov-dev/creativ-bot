from html import escape

from texts import THANKS


def format_anketa(full_name: str, data: dict) -> str:
    return (
        f"👤 <b>Ism:</b> {escape(full_name)}\n"
        f"🎂 <b>Yosh:</b> {data.get('age')}\n"
        f"💼 <b>Kasb:</b> {escape(data['job'])}\n"
        f"📝 <b>O'zi haqida:</b> {escape(data['about'])}\n"
        f"❓ <b>Qo'shilish sababi:</b> {escape(data['join_group'])}\n"
        f"{THANKS}"
    )
