"""
BLOODY MD — ULTIMATE UPGRADE PACK
Adds security, moderation, group utilities and games without replacing
the existing AI / voice / music / XP systems in handlers_admin.py.
"""

import os
import re
import time
import random
import json
from datetime import datetime

from telegram import Update, ChatPermissions
from telegram.constants import ChatMemberStatus
from telegram.ext import ContextTypes

import database as db


# ============================================================
# CORE HELPERS
# ============================================================

def _load():
    if not os.path.exists(db.DB_FILE):
        return {
            "warnings": {}, "settings": {}, "users": {},
            "active_recognition": {}, "ai_memory": {}
        }

    try:
        with open(db.DB_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        data = {}

    data.setdefault("warnings", {})
    data.setdefault("settings", {})
    data.setdefault("users", {})
    data.setdefault("active_recognition", {})
    data.setdefault("ai_memory", {})
    return data


def _save(data):
    with open(db.DB_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)


def _settings(chat_id):
    data = _load()
    key = str(chat_id)

    defaults = {
        "max_warnings": 3,
        "antispam": False,
        "antilink": False,
        "antiflood": False,
        "antiraid": False,
        "antibot": False,
        "antipromote": False,
        "antidemote": False,
        "welcome": False,
        "goodbye": False,
        "welcome_text": "👋 Welcome {name} to {chat}!",
        "goodbye_text": "👋 {name} has left the group.",
        "rules": "📜 No rules have been configured yet.",
        "locked": False,
        "slowmode": 0,
    }

    data["settings"].setdefault(key, {})
    changed = False

    for k, v in defaults.items():
        if k not in data["settings"][key]:
            data["settings"][key][k] = v
            changed = True

    if changed:
        _save(data)

    return data["settings"][key]


async def is_user_group_admin(update, context, user_id):
    chat = update.effective_chat
    if not chat or chat.type not in ("group", "supergroup"):
        return False

    try:
        member = await context.bot.get_chat_member(chat.id, user_id)
        return member.status in (
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.OWNER,
        )
    except Exception:
        return False


def extract_target_user(update):
    message = update.effective_message

    if not message:
        return None

    if message.reply_to_message and message.reply_to_message.from_user:
        return message.reply_to_message.from_user

    return None


async def bot_has_permission(update, context, permission):
    chat = update.effective_chat

    try:
        me = await context.bot.get_chat_member(chat.id, context.bot.id)
    except Exception:
        return False

    if me.status == ChatMemberStatus.OWNER:
        return True

    if me.status != ChatMemberStatus.ADMINISTRATOR:
        return False

    permissions = {
        "can_delete_messages": getattr(me, "can_delete_messages", False),
        "can_restrict_members": getattr(me, "can_restrict_members", False),
        "can_promote_members": getattr(me, "can_promote_members", False),
        "can_invite_users": getattr(me, "can_invite_users", False),
        "can_change_info": getattr(me, "can_change_info", False),
        "can_pin_messages": getattr(me, "can_pin_messages", False),
    }

    return permissions.get(permission, False)


async def admin_only(update, context):
    if not await is_user_group_admin(update, context, update.effective_user.id):
        await update.effective_message.reply_text(
            "🚫 **BLOODY SECURITY:** Admin permission required.",
            parse_mode="Markdown",
        )
        return False
    return True


async def target_guard(update, context, permission="can_restrict_members"):
    if not await admin_only(update, context):
        return None

    target = extract_target_user(update)

    if not target:
        await update.effective_message.reply_text(
            "⚠️ Reply to the member's message first."
        )
        return None

    if target.id == context.bot.id:
        await update.effective_message.reply_text(
            "😂 You can't use BLOODY's own security system against BLOODY."
        )
        return None

    if await is_user_group_admin(update, context, target.id):
        await update.effective_message.reply_text(
            "🛡️ Target is an administrator. BLOODY won't apply this action."
        )
        return None

    if permission and not await bot_has_permission(update, context, permission):
        await update.effective_message.reply_text(
            f"⚠️ I need `{permission}` permission first."
        )
        return None

    return target


async def _toggle(update, context, key, label):
    if not await admin_only(update, context):
        return

    value = context.args[0].lower() if context.args else None

    if value not in ("on", "off"):
        await update.effective_message.reply_text(
            f"⚙️ Usage: `/{key} on` or `/{key} off`",
            parse_mode="Markdown",
        )
        return

    data = _load()
    cid = str(update.effective_chat.id)
    data["settings"].setdefault(cid, {})
    data["settings"][cid][key] = value == "on"
    _save(data)

    state = "🟢 ENABLED" if value == "on" else "🔴 DISABLED"
    await update.effective_message.reply_text(
        f"🩸 **{label}**\n\n{state}",
        parse_mode="Markdown",
    )


# ============================================================
# SECURITY / ANTI-ABUSE
# ============================================================

async def antilink_command(update, context):
    await _toggle(update, context, "antilink", "ANTI-LINK")


async def antiflood_command(update, context):
    await _toggle(update, context, "antiflood", "ANTI-FLOOD")


async def antiraid_command(update, context):
    await _toggle(update, context, "antiraid", "ANTI-RAID")


async def antibot_command(update, context):
    await _toggle(update, context, "antibot", "ANTI-BOT")


async def antipromote_command(update, context):
    await _toggle(update, context, "antipromote", "ANTI-PROMOTE")


async def antidemote_command(update, context):
    await _toggle(update, context, "antidemote", "ANTI-DEMOTE")


async def lock_command(update, context):
    if not await admin_only(update, context):
        return

    data = _load()
    cid = str(update.effective_chat.id)
    data["settings"].setdefault(cid, {})
    data["settings"][cid]["locked"] = True
    _save(data)

    await update.effective_message.reply_text(
        "🔒 **GROUP LOCKED**\n\nBLOODY moderation lock is active.",
        parse_mode="Markdown",
    )


async def unlock_command(update, context):
    if not await admin_only(update, context):
        return

    data = _load()
    cid = str(update.effective_chat.id)
    data["settings"].setdefault(cid, {})
    data["settings"][cid]["locked"] = False
    _save(data)

    await update.effective_message.reply_text(
        "🔓 **GROUP UNLOCKED**\n\nNormal member messaging restored.",
        parse_mode="Markdown",
    )


async def purge_command(update, context):
    if not await admin_only(update, context):
        return

    message = update.effective_message

    if not context.args:
        await message.reply_text("⚠️ Usage: `/purge 10`", parse_mode="Markdown")
        return

    try:
        amount = max(1, min(int(context.args[0]), 100))
    except ValueError:
        await message.reply_text("❌ Enter a number from 1 to 100.")
        return

    if not await bot_has_permission(update, context, "can_delete_messages"):
        await message.reply_text("⚠️ I need delete-message permission.")
        return

    deleted = 0

    for msg_id in range(message.message_id - amount, message.message_id + 1):
        try:
            await context.bot.delete_message(message.chat_id, msg_id)
            deleted += 1
        except Exception:
            pass

    try:
        await context.bot.send_message(
            message.chat_id,
            f"🧹 Purge complete. Removed approximately {deleted} messages."
        )
    except Exception:
        pass


async def slowmode_command(update, context):
    if not await admin_only(update, context):
        return

    if not context.args:
        await update.effective_message.reply_text(
            "⚙️ Usage: `/slowmode 10` or `/slowmode off`",
            parse_mode="Markdown",
        )
        return

    value = context.args[0].lower()

    if value == "off":
        seconds = 0
    else:
        try:
            seconds = max(0, min(int(value), 900))
        except ValueError:
            await update.effective_message.reply_text(
                "❌ Slowmode must be a number from 0 to 900."
            )
            return

    try:
        await context.bot.set_chat_permissions(
            update.effective_chat.id,
            ChatPermissions(
                can_send_messages=True,
                can_send_audios=True,
                can_send_documents=True,
                can_send_photos=True,
                can_send_videos=True,
                can_send_video_notes=True,
                can_send_voice_notes=True,
                can_send_polls=True,
                can_send_other_messages=True,
                can_add_web_page_previews=True,
                can_change_info=False,
                can_invite_users=True,
                can_pin_messages=False,
            ),
        )
    except Exception:
        pass

    data = _load()
    cid = str(update.effective_chat.id)
    data["settings"].setdefault(cid, {})
    data["settings"][cid]["slowmode"] = seconds
    _save(data)

    await update.effective_message.reply_text(
        f"🐢 Slowmode configured: **{seconds}s**",
        parse_mode="Markdown",
    )


# ============================================================
# GROUP INFORMATION / CONFIG
# ============================================================

async def rules_command(update, context):
    s = _settings(update.effective_chat.id)
    await update.effective_message.reply_text(
        f"📜 **{update.effective_chat.title or 'GROUP'} RULES**\n\n{s['rules']}",
        parse_mode="Markdown",
    )


async def setrules_command(update, context):
    if not await admin_only(update, context):
        return

    text = " ".join(context.args).strip()

    if not text:
        await update.effective_message.reply_text(
            "⚠️ Usage: `/setrules Be respectful...`",
            parse_mode="Markdown",
        )
        return

    data = _load()
    cid = str(update.effective_chat.id)
    data["settings"].setdefault(cid, {})
    data["settings"][cid]["rules"] = text
    _save(data)

    await update.effective_message.reply_text("✅ Group rules updated.")


async def welcome_command(update, context):
    await _toggle(update, context, "welcome", "WELCOME SYSTEM")


async def setwelcome_command(update, context):
    if not await admin_only(update, context):
        return

    text = " ".join(context.args).strip()

    if not text:
        await update.effective_message.reply_text(
            "⚠️ Usage: `/setwelcome Welcome {name} to {chat}!`",
            parse_mode="Markdown",
        )
        return

    data = _load()
    cid = str(update.effective_chat.id)
    data["settings"].setdefault(cid, {})
    data["settings"][cid]["welcome_text"] = text
    _save(data)

    await update.effective_message.reply_text("✅ Welcome message saved.")


async def goodbye_command(update, context):
    await _toggle(update, context, "goodbye", "GOODBYE SYSTEM")


async def setgoodbye_command(update, context):
    if not await admin_only(update, context):
        return

    text = " ".join(context.args).strip()

    if not text:
        await update.effective_message.reply_text(
            "⚠️ Usage: `/setgoodbye Bye {name}!`",
            parse_mode="Markdown",
        )
        return

    data = _load()
    cid = str(update.effective_chat.id)
    data["settings"].setdefault(cid, {})
    data["settings"][cid]["goodbye_text"] = text
    _save(data)

    await update.effective_message.reply_text("✅ Goodbye message saved.")


async def admins_command(update, context):
    chat = update.effective_chat
    members = await context.bot.get_chat_administrators(chat.id)

    lines = ["👑 **GROUP ADMINISTRATORS**", ""]

    for member in members:
        name = member.user.full_name
        tag = "Owner" if member.status == ChatMemberStatus.OWNER else "Admin"
        lines.append(f"• {name} — {tag}")

    await update.effective_message.reply_text(
        "\n".join(lines),
        parse_mode="Markdown",
    )


async def id_command(update, context):
    message = update.effective_message
    target = extract_target_user(update) or update.effective_user

    await message.reply_text(
        f"🆔 **USER ID:** `{target.id}`\n"
        f"💬 **CHAT ID:** `{update.effective_chat.id}`",
        parse_mode="Markdown",
    )


async def info_command(update, context):
    target = extract_target_user(update) or update.effective_user

    try:
        member = await context.bot.get_chat_member(
            update.effective_chat.id,
            target.id,
        )
        status = member.status
    except Exception:
        status = "unknown"

    await update.effective_message.reply_text(
        f"👤 **MEMBER INFO**\n\n"
        f"Name: {target.full_name}\n"
        f"Username: @{target.username if target.username else 'none'}\n"
        f"ID: `{target.id}`\n"
        f"Status: `{status}`",
        parse_mode="Markdown",
    )


async def tagall_command(update, context):
    if not await admin_only(update, context):
        return

    await update.effective_message.reply_text(
        "📢 **TAGALL MODE**\n\n"
        "Telegram does not expose a safe one-call API for every group member. "
        "Use this command for announcement mode instead of mass-spamming mentions.",
        parse_mode="Markdown",
    )


# ============================================================
# ADMIN ACTIONS
# ============================================================

async def unban_command(update, context):
    if not await admin_only(update, context):
        return

    target = extract_target_user(update)

    if not target:
        await update.effective_message.reply_text("⚠️ Reply to the user's message.")
        return

    if not await bot_has_permission(update, context, "can_restrict_members"):
        await update.effective_message.reply_text("⚠️ I need restrict-member permission.")
        return

    try:
        await context.bot.unban_chat_member(
            update.effective_chat.id,
            target.id,
            only_if_banned=True,
        )
        await update.effective_message.reply_text(
            f"✅ {target.full_name} has been unbanned."
        )
    except Exception as e:
        await update.effective_message.reply_text(f"❌ Unban failed: {e}")


async def warn2_command(update, context):
    # Alias kept separate so /warn remains your existing system.
    target = await target_guard(update, context)
    if not target:
        return

    count = db.add_warning(update.effective_chat.id, target.id)

    await update.effective_message.reply_text(
        f"⚠️ **WARNING STRIKE**\n\n"
        f"Target: {target.full_name}\n"
        f"Strike: `{count}`",
        parse_mode="Markdown",
    )


# ============================================================
# GAMES
# ============================================================

PUZZLES = [
    ("I speak without a mouth and hear without ears. What am I?", "echo"),
    ("What has keys but can't open locks?", "keyboard"),
    ("What gets wetter the more it dries?", "towel"),
    ("What has a face and two hands but no arms or legs?", "clock"),
    ("What can travel around the world while staying in one corner?", "stamp"),
    ("What has many teeth but cannot bite?", "comb"),
]


async def wordpuzzle_command(update, context):
    question, answer = random.choice(PUZZLES)

    context.chat_data["bloody_puzzle"] = {
        "answer": answer,
        "user_id": update.effective_user.id,
    }

    await update.effective_message.reply_text(
        f"🧩 **BLOODY WORD PUZZLE**\n\n"
        f"❓ {question}\n\n"
        f"Reply with your answer.",
        parse_mode="Markdown",
    )


async def rps_command(update, context):
    choice = context.args[0].lower() if context.args else ""

    if choice not in ("rock", "paper", "scissors"):
        await update.effective_message.reply_text(
            "✊ Usage: `/rps rock` • `/rps paper` • `/rps scissors`",
            parse_mode="Markdown",
        )
        return

    bot_choice = random.choice(["rock", "paper", "scissors"])

    if choice == bot_choice:
        result = "🤝 DRAW"
    elif (
        (choice == "rock" and bot_choice == "scissors")
        or (choice == "paper" and bot_choice == "rock")
        or (choice == "scissors" and bot_choice == "paper")
    ):
        result = "🏆 YOU WIN"
        db.update_user_activity(
            update.effective_user.id,
            update.effective_user.username,
            update.effective_user.first_name,
            update.effective_chat.id,
        )
    else:
        result = "💀 BLOODY WINS"

    await update.effective_message.reply_text(
        f"🎮 **RPS MATRIX**\n\n"
        f"You: `{choice}`\n"
        f"BLOODY: `{bot_choice}`\n\n"
        f"**{result}**",
        parse_mode="Markdown",
    )


async def coinflip_command(update, context):
    result = random.choice(["HEADS", "TAILS"])
    await update.effective_message.reply_text(
        f"🪙 **COIN FLIP**\n\nResult: **{result}**",
        parse_mode="Markdown",
    )


async def dice_command(update, context):
    value = random.randint(1, 6)
    await update.effective_message.reply_text(
        f"🎲 **DICE MATRIX**\n\nYou rolled: **{value}**",
        parse_mode="Markdown",
    )


async def slots_command(update, context):
    symbols = ["🍒", "🍋", "🍇", "⭐", "💎", "7️⃣"]
    roll = [random.choice(symbols) for _ in range(3)]

    if len(set(roll)) == 1:
        result = "💎 JACKPOT!"
    elif len(set(roll)) == 2:
        result = "✨ Nice hit!"
    else:
        result = "💀 No match."

    await update.effective_message.reply_text(
        f"🎰 **BLOODY SLOTS**\n\n"
        f"{' | '.join(roll)}\n\n{result}",
        parse_mode="Markdown",
    )


# ============================================================
# STATUS / FUN
# ============================================================

async def botstatus_command(update, context):
    await update.effective_message.reply_text(
        "🩸 **BLOODY MD STATUS**\n\n"
        "🟢 Core: ONLINE\n"
        "🟢 AI: ONLINE\n"
        "🟢 Voice: ONLINE\n"
        "🟢 Games: ONLINE\n"
        "🟢 Moderation: ONLINE",
        parse_mode="Markdown",
    )


async def settings_command(update, context):
    s = _settings(update.effective_chat.id)

    def mark(v):
        return "🟢 ON" if v else "🔴 OFF"

    await update.effective_message.reply_text(
        "⚙️ **BLOODY GROUP SETTINGS**\n\n"
        f"Anti-link: {mark(s['antilink'])}\n"
        f"Anti-flood: {mark(s['antiflood'])}\n"
        f"Anti-raid: {mark(s['antiraid'])}\n"
        f"Anti-bot: {mark(s['antibot'])}\n"
        f"Anti-promote: {mark(s['antipromote'])}\n"
        f"Anti-demote: {mark(s['antidemote'])}\n"
        f"Welcome: {mark(s['welcome'])}\n"
        f"Goodbye: {mark(s['goodbye'])}\n"
        f"Lock: {mark(s['locked'])}\n"
        f"Slowmode: {s['slowmode']}s",
        parse_mode="Markdown",
    )


async def quote_command(update, context):
    message = update.effective_message

    if not message.reply_to_message:
        await message.reply_text("⚠️ Reply to a message to quote it.")
        return

    source = message.reply_to_message
    text = source.text or source.caption or "Media message"

    await message.reply_text(
        f"💬 **QUOTE MATRIX**\n\n"
        f"“{text[:1000]}”\n\n"
        f"— {source.from_user.full_name if source.from_user else 'Unknown'}",
        parse_mode="Markdown",
    )


async def announce_command(update, context):
    if not await admin_only(update, context):
        return

    text = " ".join(context.args).strip()

    if not text:
        await update.effective_message.reply_text(
            "⚠️ Usage: `/announce Your announcement`",
            parse_mode="Markdown",
        )
        return

    await context.bot.send_message(
        update.effective_chat.id,
        f"📢 **BLOODY ANNOUNCEMENT**\n\n{text}",
        parse_mode="Markdown",
    )


# ============================================================
# AUTOMATIC MESSAGE PROTECTION
# ============================================================

LINK_RE = re.compile(
    r"(https?://|www\.|t\.me/|telegram\.me/|discord\.gg/|"
    r"\b[\w-]+\.(com|net|org|io|xyz|co|ng|me)\b)",
    re.IGNORECASE,
)

FLOOD_CACHE = {}


async def protection_message_handler(update, context):
    message = update.effective_message
    chat = update.effective_chat

    if not message or not chat or chat.type not in ("group", "supergroup"):
        return

    user = update.effective_user
    if not user:
        return

    if await is_user_group_admin(update, context, user.id):
        return

    settings = _settings(chat.id)

    # Anti-link
    text = message.text or message.caption or ""

    if settings.get("antilink") and LINK_RE.search(text):
        if await bot_has_permission(update, context, "can_delete_messages"):
            try:
                await message.delete()
            except Exception:
                pass
        return

    # Anti-flood: 6 messages inside 5 seconds
    if settings.get("antiflood"):
        now = time.time()
        key = (chat.id, user.id)

        bucket = FLOOD_CACHE.setdefault(key, [])
        bucket[:] = [t for t in bucket if now - t < 5]
        bucket.append(now)

        if len(bucket) >= 6:
            if await bot_has_permission(update, context, "can_restrict_members"):
                try:
                    await context.bot.restrict_chat_member(
                        chat.id,
                        user.id,
                        permissions=ChatPermissions(can_send_messages=False),
                        until_date=int(now + 60),
                    )
                except Exception:
                    pass
            FLOOD_CACHE[key] = []


async def new_member_handler(update, context):
    chat = update.effective_chat
    s = _settings(chat.id)

    if not update.chat_member:
        return

    old_status = update.chat_member.old_chat_member.status
    new_status = update.chat_member.new_chat_member.status
    user = update.chat_member.new_chat_member.user

    # Anti-bot
    if (
        s.get("antibot")
        and new_status in (
            ChatMemberStatus.MEMBER,
            ChatMemberStatus.RESTRICTED,
        )
        and user.is_bot
    ):
        if await bot_has_permission(update, context, "can_restrict_members"):
            try:
                await context.bot.ban_chat_member(chat.id, user.id)
            except Exception:
                pass
        return

    # Welcome
    joined = old_status in (
        ChatMemberStatus.LEFT,
        ChatMemberStatus.KICKED,
    ) and new_status in (
        ChatMemberStatus.MEMBER,
        ChatMemberStatus.RESTRICTED,
    )

    if joined and s.get("welcome"):
        text = s["welcome_text"].format(
            name=user.full_name,
            chat=chat.title or "this group",
        )
        await context.bot.send_message(chat.id, f"👋 {text}")


# ============================================================
# FANCY MENU
# ============================================================

async def ultimate_menu_command(update, context):
    menu = r"""
╔══════════════════════════════════╗
║        🩸  B L O O D Y  M D      ║
║       ⚡ ULTIMATE COMMAND HUB ⚡   ║
╚══════════════════════════════════╝

╭━━━ 🧠 AI & CORE ━━━╮
│ /start /menu /ping
│ /play /rank /top
│ /claim /recognize
│ /botstatus /settings
╰━━━━━━━━━━━━━━━━━━╯

╭━━━ 🎮 GAMES ━━━╮
│ /trivia /truth /dare
│ /gamble /steal /duel
│ /wordpuzzle /rps
│ /coinflip /dice /slots
╰━━━━━━━━━━━━━━━╯

╭━━━ 🛡️ MODERATION ━━━╮
│ /warn /warnings /clearwarns
│ /mute /unmute /kick /ban /unban
│ /purge /lock /unlock
│ /slowmode /antispam
│ /antilink /antiflood
│ /antiraid /antibot
│ /antipromote /antidemote
╰━━━━━━━━━━━━━━━━━━━━╯

╭━━━ 👑 ADMIN TOOLS ━━━╮
│ /badge /promote /demote
│ /givexp /poll
│ /announce /admins
│ /tagall /id /info
╰━━━━━━━━━━━━━━━━━━╯

╭━━━ 👥 GROUP SYSTEM ━━━╮
│ /rules /setrules
│ /welcome /setwelcome
│ /goodbye /setgoodbye
│ /quote
╰━━━━━━━━━━━━━━━━━━╯

🩸 BLOODY MD

⚡ AI • VOICE • XP • MUSIC • GAMES
🛡️ SECURITY • MODERATION • GROUP TOOLS
"""
    await update.effective_message.reply_text(menu)