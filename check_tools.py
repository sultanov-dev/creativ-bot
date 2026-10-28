"""Tool calling'ni qo'lda sinash (JSON protokol): python check_tools.py ["xabar"]
URL va tokenni ekranga chiqarmaydi; .env dan o'qiydi."""
import asyncio
import json
import os
import sys

import aiohttp
from dotenv import load_dotenv

load_dotenv(".env")
URL, TOKEN, MODEL = os.getenv("API_URL", ""), os.getenv("API_TOKEN", ""), os.getenv("API_MODEL", "")
USER_TEXT = sys.argv[1] if len(sys.argv) > 1 else "admin bilan gaplashmoqchiman"

PROTOCOL = (
    "Respond with ONE JSON object and nothing else (no Markdown, no code fence): "
    '{"reply": "<text for the user, or an empty string>", "tool": "<tool name, or null>", "arguments": {...}}. '
    'Use "tool" only when a tool below must be called, otherwise set it to null. '
    "Escape double quotes inside strings. Available tools:\n"
    "- contact_admin: The user wants to talk to an admin, moderator or the group owner "
    "(any wording or language, also indirectly). Call it instead of answering in the group. "
    'Arguments (JSON schema): {"type": "object", "properties": {"reason": {"type": "string", '
    '"description": "Why the user wants an admin, briefly."}}}'
)
PAYLOAD = {
    "messages": [
        {
            "role": "system",
            "content": "You are an assistant in a Telegram group. If the user wants to talk to an admin, "
            "moderator or the group owner (any wording or language, also indirectly), call the contact_admin "
            "tool and write no reply text.",
        },
        {"role": "user", "content": USER_TEXT},
        {"role": "system", "content": PROTOCOL},
    ],
    "max_tokens": 900,
}
if MODEL:
    PAYLOAD["model"] = MODEL


async def main():
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60)) as s:
        async with s.post(URL, json=PAYLOAD, headers={"Authorization": f"Bearer {TOKEN}"}) as r:
            body = await r.text()
            print("HTTP", r.status)
            try:
                data = json.loads(body)
                print("finish_reason:", data["choices"][0].get("finish_reason"))
                print("message:", json.dumps(data["choices"][0]["message"], ensure_ascii=False, indent=2))
            except (ValueError, KeyError, IndexError, TypeError):
                print("javob:", body[:1500])


asyncio.run(main())
