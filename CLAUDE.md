# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

Telegram bot (aiogram 3, Python, SQLite via aiosqlite). No tests, linter or build step are configured.

```bash
python -m venv venv && source venv/bin/activate   # venv/ is gitignored
pip install -r requirements.txt
cp .env.example .env                              # then fill in values
python main.py                                    # long polling; creates bot.db on first run
```

Docker: `docker compose up -d --build` runs the bot; `bot.db` lives in the `bot-data` volume (`DATA_DIR=/data`, default `.` locally).

Env vars (read in `config.py`): `BOT_TOKEN`, `DEVELOPER_IDS` (optional, comma-separated: uncaught handler errors are logged and DMed to these developers with update/chat/user context by `handlers/errors.py`, never to group admins; group admins always come from the group itself), `REQUIRED_VOTES` (default 100), `API_URL` (AI xizmatining base URL'i), `API_TOKEN` (Bearer token), `API_PATH` (default `/chat/completions`), `API_MODEL` (default `chat/answer`). Logging: `utils/logging_setup.py` (console + rotating `DATA_DIR/logs/bot.log`, level via optional `LOG_LEVEL`); `utils/request_log.py` logs every incoming update (`tg.in`, free-text answers only by length — they are personal data) and every Telegram API call/response (`tg.out`, `GetUpdates` only at DEBUG). There is deliberately no group ID in config: the bot is deployed into whatever group it is added to, and the group is always taken from the update (join request chat, `my_chat_member`, message chat).

## Architecture

The bot gates entry to a Telegram group: a user who requests to join fills in a questionnaire (anketa) in a private chat, group admins approve/reject it, and approved applications go to a group-wide vote.

Flow across files (it spans several, so read them together):

1. `handlers/join.py` — `chat_join_request` handler. Greets the user via DM and sets FSM state `Form.age` **for the private chat** using `utils/fsm.get_private_state` (the update comes from the group context, so the state key must be built manually). It stores `group_id` in FSM data so later steps know which group the application is for.
2. `handlers/anketa.py` — private-chat FSM steps (`states.Form`: age → job → about → join_group). On the last step it formats the anketa, inserts an `applications` row, and DMs every non-bot group admin with `keyboards/action.py` inline buttons (`ApplicantCB`).
3. `handlers/admin.py` — `accept`/`reject` callbacks. Verifies the clicker is a group admin, then transitions status atomically with `database.change_status(old, new)` (`UPDATE ... WHERE status = old`, so double-clicks are rejected). `reject` declines the join request; `accept` moves to `voting` and posts a vote message with `keyboards/vote.py` (`VoteCB`) into the group, saving `vote_message_id`.
4. `handlers/vote.py` — `on_vote` records one vote per group member (`votes` table, applicant can't vote on own application), refreshes the button counters, and finalizes when `yes >= REQUIRED_VOTES` (approve join request) or `no >= REQUIRED_VOTES` (decline).

5. `handlers/reason.py` + `utils/reasons.py` — a 👎 vote makes the bot DM the voter asking for a reason (if the DM fails, the voter is told to `/start` the bot and `handlers/start.py` re-asks). The reply is matched to the voter's latest reason-less 👎 vote from the last 24h (`database.get_pending_reason`, no FSM). Each reason is DMed to the group admins immediately (`utils/reasons.send_to_admins`), without waiting for voting to finish.

6. `handlers/group.py` — group moderation commands (`/kick_deleted`, `/ban`, `/unban`, `/mute`, `/unmute`, `/stats`). A router-level `creator_only` filter means only the group creator is obeyed; everyone else is silently ignored. The Bot API cannot list group members, so `/kick_deleted` only checks members the bot has *seen*: `utils/members.TrackMembersMiddleware` (all group messages, join/leave service messages) and the `chat_member` handler record them in the `members` table. The command re-fetches each tracked member and kicks (ban + unban) those whose first name is "Deleted Account". Old silent members the bot never saw are not covered — an earlier Telethon userbot approach was dropped on purpose (personal-account session risk).

7. `handlers/ai.py` + `utils/ai.py` — AI assistant in groups. A message that mentions the bot (`@bot ...`) or replies to one of the bot's earlier AI answers is sent to an OpenAI-format `chat/completions` API (`ask_ai`, aiohttp, `API_URL` + `API_PATH`, Bearer `API_TOKEN`) and the answer is sent back as a reply (plain text, split at 4096 chars). Conversation memory is only the replied-to AI answer (Telegram gives one reply level); AI answer ids are kept in memory (`_ai_messages`, lost on restart). Per-user 5s cooldown. `AIError` replies with a generic message, then re-raises so `handlers/errors.py` DMs the developers. Never log `API_TOKEN`.

Application status lifecycle: `pending` → `rejected` | `voting` → `accepted` | `rejected`.

Supporting pieces:
- `handlers/__init__.py:get_routers()` — router registration order matters; add new routers there.
- `callbacks.py` — `CallbackData` factories; `texts.py` — user-facing message constants; `utils/` — bot instance (`create_bot.py`), `safe_send`/`is_group_admin`/`mark_done` helpers (`admin.py`), typing-delay sender, number extraction, anketa formatting.
- `database.py` — every function opens its own `aiosqlite.connect(DB_PATH)` connection (`bot.db` in the cwd, gitignored via `*.db`); FSM state/data also live in `bot.db` (`fsm` table, `utils/fsm_storage.SQLiteStorage`) so half-filled anketas survive restarts; schema is created by `init_db()` with `CREATE TABLE IF NOT EXISTS`, so schema changes need a manual migration.
- All user-facing text is in Uzbek; keep new messages and log strings consistent with that.
