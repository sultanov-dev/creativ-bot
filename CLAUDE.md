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

Env vars (read in `config.py`): `BOT_TOKEN`, `ADMIN_IDS` (comma-separated), `GROUP_ID`, `REQUIRED_VOTES` (default 100).

## Architecture

The bot gates entry to a Telegram group: a user who requests to join fills in a questionnaire (anketa) in a private chat, group admins approve/reject it, and approved applications go to a group-wide vote.

Flow across files (it spans several, so read them together):

1. `handlers/join.py` — `chat_join_request` handler. Greets the user via DM and sets FSM state `Form.age` **for the private chat** using `utils/fsm.get_private_state` (the update comes from the group context, so the state key must be built manually). It stores `group_id` in FSM data so later steps know which group the application is for.
2. `handlers/anketa.py` — private-chat FSM steps (`states.Form`: age → job → about → join_group). On the last step it formats the anketa, inserts an `applications` row, and DMs every non-bot group admin with `keyboards/action.py` inline buttons (`ApplicantCB`).
3. `handlers/admin.py` — `accept`/`reject` callbacks. Verifies the clicker is a group admin, then transitions status atomically with `database.change_status(old, new)` (`UPDATE ... WHERE status = old`, so double-clicks are rejected). `reject` declines the join request; `accept` moves to `voting` and posts a vote message with `keyboards/vote.py` (`VoteCB`) into the group, saving `vote_message_id`.
4. `handlers/vote.py` — `on_vote` records one vote per group member (`votes` table, applicant can't vote on own application), refreshes the button counters, and finalizes when `yes >= REQUIRED_VOTES` (approve join request) or `no >= REQUIRED_VOTES` (decline).

Application status lifecycle: `pending` → `rejected` | `voting` → `accepted` | `rejected`.

Supporting pieces:
- `handlers/__init__.py:get_routers()` — router registration order matters; add new routers there.
- `callbacks.py` — `CallbackData` factories; `texts.py` — user-facing message constants; `utils/` — bot instance (`create_bot.py`), `safe_send`/`is_group_admin`/`mark_done` helpers (`admin.py`), typing-delay sender, number extraction, anketa formatting.
- `database.py` — every function opens its own `aiosqlite.connect(DB_PATH)` connection (`bot.db` in the cwd, gitignored via `*.db`); schema is created by `init_db()` with `CREATE TABLE IF NOT EXISTS`, so schema changes need a manual migration.
- All user-facing text is in Uzbek; keep new messages and log strings consistent with that.
