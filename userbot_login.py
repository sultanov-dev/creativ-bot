"""Userbot sessiyasini bir marta yaratadi: telefon raqam va Telegram kodi so'raladi.

Ishga tushirish: python userbot_login.py
Natijada `userbot.session` fayli yaratiladi, uni hech kimga bermang va commit qilmang.
"""

from telethon import TelegramClient

from config import API_HASH, API_ID, USERBOT_SESSION

if not (API_ID and API_HASH):
    raise SystemExit(".env da API_ID va API_HASH ni to'ldiring (my.telegram.org)")

with TelegramClient(USERBOT_SESSION, API_ID, API_HASH) as client:
    me = client.loop.run_until_complete(client.get_me())
    print(f"Sessiya tayyor: {me.first_name} (id={me.id})")
