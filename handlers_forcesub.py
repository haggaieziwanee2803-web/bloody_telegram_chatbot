# ============================================================
# handlers_forcesub.py
# BLOODY MD — FORCE SUBSCRIBE GATE
#
# Requires users to join your channel(s)/group(s) before they
# can use the bot in a PRIVATE chat. Group chats are NOT gated
# (people already had to join the group to talk to the bot there).
#
# SETUP REQUIRED:
# 1. Add your bot as an ADMIN in every channel/group listed below.
#    (Telegram only lets a bot check membership if it's an admin
#    there, or if the channel is public.)
# 2. Fill in FORCE_SUB_CHANNELS below with your real channels/groups.
#
# IMPORTANT — WHY THIS SILENTLY "STOPPED WORKING" BEFORE:
# If the bot can't check a channel (wrong ID, bot not a member/admin
# there, chat renamed, etc.) it FAILS OPEN — it does NOT block the
# user, on purpose, so one bad entry doesn't lock everyone out. But
# the error was only ever `print()`-ed, which never reaches
# logs/bot.log (that file is fed by the `logging` module, not
# stdout `print`), so on a VPS running in the background you'd
# never see it — it looks like the gate is just "off". That's now
# fixed: errors go through `logging`, and `run_startup_diagnostics`
# below checks all three chats the moment the bot boots and logs
# exactly which one(s) are broken.
# ============================================================

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationHandlerStop

logger = logging.getLogger(__name__)


# ============================================================
# CONFIG — edit this list with your real channels/groups
# ============================================================
#
# "chat_id" is what the bot uses internally to check membership.
#   - For a PUBLIC channel/group: use "@yourusername"
#   - For a PRIVATE channel/group: use its numeric ID (starts with -100...)
#     You can get this by adding @userinfobot or @RawDataBot to the
#     channel/group temporarily, or by checking your bot's logs
#     the first time it sees a message from that chat.
#
# "join_url" is the link shown on the button.
#   - For a PUBLIC channel/group: "https://t.me/yourusername"
#   - For a PRIVATE channel/group: use an invite link you generate
#     from the channel/group's admin settings (Invite Links).

FORCE_SUB_CHANNELS = [
    {
        "name": "Devil's domain",
        "chat_id": "@justforfun3668",
        "join_url": "https://t.me/justforfun3668",
    },
    {
        "name": "Devil's domain 2",
        "chat_id": "@bloodyhazybotgroup",
        "join_url": "https://t.me/bloodyhazybotgroup"
    },
    {
        "name": "The unarchives",
        "chat_id": "@eunicedomain",
        "join_url": "https://t.me/eunicedomain"
    },
    {
        "name": "DEITY BLOODY's DOMAIN",
        "chat_id": "@deitybloodydomain",
        "join_url": "https://t.me/deitybloodydomain"
    },
]


# ============================================================
# STARTUP DIAGNOSTICS
# Call this once from bot.py right after the Application is built.
# It doesn't check any particular user — it just confirms the BOT
# ITSELF can see each configured chat, which is a precondition for
# checking any user's membership at all. Logs a clear ✅/❌ per
# entry so a bad chat_id or a missing admin/membership stands out
# immediately in your console/logs instead of failing invisibly
# every time a real user hits the gate.
# ============================================================

async def run_startup_diagnostics(bot):
    logger.info("[FORCESUB] Running startup diagnostics on configured channels...")

    any_broken = False

    for channel in FORCE_SUB_CHANNELS:
        try:
            chat = await bot.get_chat(channel["chat_id"])

            me = await bot.get_me()
            member = await bot.get_chat_member(
                chat_id=channel["chat_id"],
                user_id=me.id
            )

            logger.info(
                "[FORCESUB] OK — '%s' (%s) reachable, bot status there: %s",
                channel["name"],
                channel["chat_id"],
                member.status,
            )

        except Exception as error:
            any_broken = True
            logger.error(
                "[FORCESUB] BROKEN — '%s' (%s) could not be checked: %s. "
                "The join-gate is currently NOT enforcing this entry — "
                "make sure the bot has been added to that chat, that the "
                "@username/ID is correct, and that the chat still exists.",
                channel["name"],
                channel["chat_id"],
                error,
            )

    if not any_broken:
        logger.info("[FORCESUB] All configured channels are reachable.")


# ============================================================
# MEMBERSHIP CHECK
# ============================================================

async def _get_unjoined_channels(bot, user_id):
    unjoined = []

    for channel in FORCE_SUB_CHANNELS:
        try:
            member = await bot.get_chat_member(
                chat_id=channel["chat_id"],
                user_id=user_id
            )

            if member.status not in ("member", "administrator", "creator"):
                unjoined.append(channel)

        except Exception as error:
            # If the bot can't check (e.g. not admin there, wrong ID),
            # fail safe by NOT blocking the user, but log it clearly so
            # you notice the misconfiguration (see run_startup_diagnostics
            # above for a proactive version of this same check).
            logger.warning(
                "[FORCESUB] Couldn't check '%s' (%s) for user %s: %s",
                channel["name"],
                channel["chat_id"],
                user_id,
                error,
            )

    return unjoined


def _build_join_keyboard(unjoined_channels):
    rows = [
        [InlineKeyboardButton(f"📢 Join {c['name']}", url=c["join_url"])]
        for c in unjoined_channels
    ]

    rows.append([
        InlineKeyboardButton("✅ I've Joined", callback_data="forcesub_check")
    ])

    return InlineKeyboardMarkup(rows)


# ============================================================
# GATE — runs before every other handler in private chats
# ============================================================

async def force_sub_gate(update, context):
    message = update.effective_message
    chat = update.effective_chat
    user = update.effective_user

    if not message or not chat or not user:
        return

    # Only gate private (DM) usage — groups are unaffected.
    if chat.type != "private":
        return

    unjoined = await _get_unjoined_channels(context.bot, user.id)

    if not unjoined:
        return  # user has joined everything, let the update through

    await message.reply_text(
        "🚫 **Access Restricted**\n\n"
        "You need to join the channel(s)/group(s) below before "
        "using this bot:",
        parse_mode="Markdown",
        reply_markup=_build_join_keyboard(unjoined)
    )

    # Stops this update from reaching any other handler
    # (commands, AI chat, etc.)
    raise ApplicationHandlerStop


# ============================================================
# "I've Joined" BUTTON CALLBACK
# ============================================================

async def force_sub_check_callback(update, context):
    query = update.callback_query
    user = update.effective_user

    unjoined = await _get_unjoined_channels(context.bot, user.id)

    if unjoined:
        await query.answer(
            "❌ You haven't joined everything yet. Please join and try again.",
            show_alert=True
        )
        return

    await query.answer("✅ Verified! You can now use the bot.")

    try:
        await query.edit_message_text(
            "✅ **Verified!**\n\nYou now have full access. Send /menu to get started.",
            parse_mode="Markdown"
        )
    except Exception:
        pass