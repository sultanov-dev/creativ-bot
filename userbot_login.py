"""Userbot sessiyasini bir marta yaratadi.

Ishga tushirish: python userbot_login.py
Telefon raqamingizni (+998...) kiriting, so'ng Telegram yuborgan kodni. BOT TOKENNI KIRITMANG.
Natijada `userbot.session` fayli yaratiladi, uni hech kimga bermang va commit qilmang.
"""

import os

from telethon import TelegramClient

from config import API_HASH, API_ID, USERBOT_SESSION

if not (API_ID and API_HASH):
    raise SystemExit(".env da API_ID va API_HASH ni to'ldiring (my.telegram.org)")

client = TelegramClient(USERBOT_SESSION, API_ID, API_HASH)

with client:
    me = client.loop.run_until_complete(client.get_me())
    is_bot = me.bot

if is_bot:
    os.remove(f"{USERBOT_SESSION}.session")
    raise SystemExit(
        "Sessiya bot tokeni bilan yaratilgan edi va o'chirildi. "
        "Skriptni qayta ishga tushirib, telefon raqamingizni kiriting."
    )

print(f"Sessiya tayyor: {me.first_name} (id={me.id})")
