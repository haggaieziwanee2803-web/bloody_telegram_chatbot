# ============================================================
# handlers_greetings.py
# BLOODY MD — AUTOMATIC DAILY GREETINGS
#
# Sends a greeting message automatically every day at set times,
# to whichever chats you list below. Uses PTB's JobQueue, which
# runs in the background — no extra setup beyond installing the
# job-queue extra (see note at the bottom of this file).
# ============================================================

import json
import os
import random
from datetime import time as dtime
from zoneinfo import ZoneInfo

LAGOS_TZ = ZoneInfo("Africa/Lagos")

# ============================================================
# CONFIG — any extra chats you always want greeted (e.g. a
# public channel), on top of every group the bot is a member
# of (which is now tracked automatically — see KNOWN GROUPS
# below). Use "@yourchannel" for public ones, or the numeric
# chat_id (starts with -100...) for private ones. This can be
# left empty; it's just for chats outside the auto-tracked list.
# ============================================================

GREETING_CHAT_IDS = [
    "@justforfun3668",
    
]

MORNING_MESSAGES = [
    "☀️ **GOOD MORNING FAM!** 🩸\n\nRise and grind — a new day, a new chance to top the leaderboard. Let's get it!",
    "🌅 **Morning, Bloody Family!**\n\nCoffee in one hand, ambition in the other. Let's make today count. ☕🔥",
]

AFTERNOON_MESSAGES = [
    "🌤️ **Good afternoon, everyone!**\n\nHow's the day treating you? Take a break, run `/trivia`, and grab some free XP. 🧠",
    "🕑 **Afternoon check-in!** 🩸\n\nHope you're crushing it today. Don't forget to `/claim` your daily XP if you haven't!",
]

NIGHT_MESSAGES = [
    "🌙 **Good night, Bloody Family!** 🩸\n\nRest up — tomorrow's another day to climb the ranks. See you at the top. 🌌",
    "🌃 **Winding down for the night?**\n\nGreat day, everyone. Sleep well and come back stronger tomorrow. 💤🩸",
]


# ============================================================
# KNOWN GROUPS — a small persisted registry of every group the
# bot is currently in, built automatically (no manual list to
# maintain). Two ways a group lands in here:
#
#   1. track_chat_membership() — fires the instant the bot is
#      added to (or removed from) a group.
#   2. track_group_activity() — a passive safety net that notes
#      a group's chat_id the first time the bot sees any message
#      in it, so groups the bot was already sitting in before this
#      tracking existed still get picked up.
# ============================================================

KNOWN_GROUPS_FILE = "data/known_groups.json"

os.makedirs("data", exist_ok=True)


def _load_known_group_ids():
    if not os.path.exists(KNOWN_GROUPS_FILE):
        return set()

    try:
        with open(KNOWN_GROUPS_FILE, "r", encoding="utf-8") as file:
            return set(json.load(file))
    except Exception as error:
        print(f"[GREETINGS] Couldn't load known groups: {error}")
        return set()


def _save_known_group_ids(ids):
    try:
        with open(KNOWN_GROUPS_FILE, "w", encoding="utf-8") as file:
            json.dump(list(ids), file)
    except Exception as error:
        print(f"[GREETINGS] Couldn't save known groups: {error}")


_KNOWN_GROUPS = _load_known_group_ids()


def note_active_chat(chat):
    """Passive safety net: call with any update's chat to make sure
    every group the bot is in ends up in the registry, even ones it
    was already a member of before this tracking existed."""

    if not chat or chat.type not in ("group", "supergroup"):
        return

    if chat.id not in _KNOWN_GROUPS:
        _KNOWN_GROUPS.add(chat.id)
        _save_known_group_ids(_KNOWN_GROUPS)


async def track_group_activity(update, context):
    note_active_chat(update.effective_chat)


async def track_chat_membership(update, context):
    """Fires the moment the bot's own membership status changes in a
    chat (added, removed, promoted, etc.) — keeps the registry
    accurate going forward without waiting on regular traffic."""

    result = update.my_chat_member

    if not result:
        return

    chat = result.chat

    if not chat or chat.type not in ("group", "supergroup"):
        return

    new_status = result.new_chat_member.status

    if new_status in ("member", "administrator", "creator"):
        if chat.id not in _KNOWN_GROUPS:
            _KNOWN_GROUPS.add(chat.id)
            _save_known_group_ids(_KNOWN_GROUPS)

    elif new_status in ("left", "kicked"):
        if chat.id in _KNOWN_GROUPS:
            _KNOWN_GROUPS.discard(chat.id)
            _save_known_group_ids(_KNOWN_GROUPS)


def _all_greeting_targets():
    # Every group the bot is currently known to be in, plus any
    # extra chats explicitly listed above (deduplicated).
    return list(_KNOWN_GROUPS) + [
        chat_id for chat_id in GREETING_CHAT_IDS
        if chat_id not in _KNOWN_GROUPS
    ]


async def _send_to_all(bot, messages):
    text = random.choice(messages)

    for chat_id in _all_greeting_targets():
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode="Markdown"
            )
        except Exception as error:
            print(f"[GREETINGS] Couldn't send to {chat_id}: {error}")


async def send_morning_greeting(context):
    await _send_to_all(context.bot, MORNING_MESSAGES)


async def send_afternoon_greeting(context):
    await _send_to_all(context.bot, AFTERNOON_MESSAGES)


async def send_night_greeting(context):
    await _send_to_all(context.bot, NIGHT_MESSAGES)


def register_greeting_jobs(app):
    """Call this once from bot.py after building the Application."""

    app.job_queue.run_daily(
        send_morning_greeting,
        time=dtime(hour=7, minute=0, tzinfo=LAGOS_TZ),
        name="morning_greeting",
    )

    app.job_queue.run_daily(
        send_afternoon_greeting,
        time=dtime(hour=13, minute=0, tzinfo=LAGOS_TZ),
        name="afternoon_greeting",
    )

    app.job_queue.run_daily(
        send_night_greeting,
        time=dtime(hour=21, minute=0, tzinfo=LAGOS_TZ),
        name="night_greeting",
    )


# ============================================================
# SETUP NOTE
#
# JobQueue needs an extra dependency. Install it with:
#
#   pip install "python-telegram-bot[job-queue]"
#
# If you already installed python-telegram-bot without the
# [job-queue] extra, run that command again — it adds APScheduler
# on top of what you have, nothing gets removed.
# ============================================================