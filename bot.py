# ============================================================
# bot.py
# BLOODY MD — MAIN ENTRY POINT
# ============================================================

import logging
import os
import random
from logging.handlers import RotatingFileHandler

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ChatMemberHandler,
    filters,
)

import handlers_admin as h
import handlers_media as media
import handlers_forcesub as forcesub
import handlers_greetings as greetings
from config import BOT_TOKEN


# ============================================================
# LOGGING
#
# Writes to BOTH the console (so you see it live) and to a
# rotating log file (so you can check what happened while you
# were away). "Rotating" means it caps each file at 5MB and
# keeps 5 old ones, so logs never grow forever and fill your disk.
# ============================================================

os.makedirs("logs", exist_ok=True)

log_formatter = logging.Formatter(
    "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

file_handler = RotatingFileHandler(
    "logs/bot.log",
    maxBytes=5 * 1024 * 1024,  # 5MB per file
    backupCount=5,
    encoding="utf-8",
)
file_handler.setFormatter(log_formatter)

console_handler = logging.StreamHandler()
console_handler.setFormatter(log_formatter)

root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
root_logger.addHandler(file_handler)
root_logger.addHandler(console_handler)

# Quiet down noisy third-party libraries so your log file stays
# readable — they'll still log warnings/errors, just not every
# single successful HTTP request.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


# ============================================================
# SHUTDOWN — closes the aiohttp session used by handlers_media
# ============================================================

async def on_shutdown(application):
    await media.close_media_session()


# ============================================================
# STARTUP — runs once the bot is up and polling
# ============================================================

async def on_startup(application):
    # Confirms the bot can actually see every configured force-sub
    # channel/group RIGHT NOW, and logs exactly which ones are
    # broken instead of failing silently forever (see the comment
    # block at the top of handlers_forcesub.py for why this matters).
    await forcesub.run_startup_diagnostics(application.bot)

    # Kicks off the recurring "random XP gift" drop. The job
    # reschedules itself every time it runs (see drop_random_gift_job),
    # so this just needs to fire once to get the cycle going.
    first_delay = random.randint(
        h.GIFT_MIN_INTERVAL_SECONDS,
        h.GIFT_MAX_INTERVAL_SECONDS
    )

    application.job_queue.run_once(
        h.drop_random_gift_job,
        first_delay
    )

    logger.info(
        f"[GIFT] First XP-gift drop scheduled in ~{first_delay // 60} minutes."
    )


# ============================================================
# GLOBAL ERROR HANDLER
# Catches any exception that escapes a handler so a single bad
# error can't crash the whole bot silently. Logged to logs/bot.log.
# ============================================================

async def on_error(update, context):
    logger.error(
        "Unhandled exception while processing update: %s",
        update,
        exc_info=context.error,
    )


# ============================================================
# MAIN
# ============================================================

def main():
    token = os.environ.get("BOT_TOKEN") or BOT_TOKEN

    app = (
        ApplicationBuilder()
        .token(token)
        # Fixes "one user waits for another" — lets PTB process
        # updates concurrently instead of strictly one at a time.
        .concurrent_updates(True)
        .post_init(on_startup)
        .post_shutdown(on_shutdown)
        .build()
    )

    app.add_error_handler(on_error)

    # --------------------------------------------------------
    # AUTOMATIC DAILY GREETINGS (morning / afternoon / night)
    # --------------------------------------------------------
    greetings.register_greeting_jobs(app)

    # Keeps the "which groups is the bot in" list accurate:
    # fires instantly when the bot is added to / removed from a
    # group, and passively notes any group it's already in the
    # first time it sees a message there.
    app.add_handler(
        ChatMemberHandler(
            greetings.track_chat_membership,
            ChatMemberHandler.MY_CHAT_MEMBER
        )
    )

    # Separate group (3) so it always runs alongside the greeting
    # tracker above instead of being skipped if that one matches
    # first. Feeds the known-chats registry that /broadcast and
    # the XP-gift drop rely on to know which groups to use.
    app.add_handler(
        ChatMemberHandler(
            h.track_known_chat_membership,
            ChatMemberHandler.MY_CHAT_MEMBER
        ),
        group=3
    )

    app.add_handler(
        MessageHandler(filters.ALL, greetings.track_group_activity),
        group=2
    )

    # --------------------------------------------------------
    # FORCE-SUBSCRIBE GATE
    # Runs BEFORE every other handler, in group -1.
    # Only blocks PRIVATE chats — groups are unaffected.
    # --------------------------------------------------------
    app.add_handler(
        MessageHandler(filters.ALL, forcesub.force_sub_gate),
        group=-1
    )

    app.add_handler(
        CallbackQueryHandler(
            forcesub.force_sub_check_callback,
            pattern="^forcesub_check$"
        )
    )

    # --------------------------------------------------------
    # GENERAL
    # --------------------------------------------------------
    app.add_handler(CommandHandler("menu", h.menu_command))
    app.add_handler(CommandHandler("rank", h.rank_command))
    app.add_handler(CommandHandler("top", h.top_command))
    app.add_handler(CommandHandler("claim", h.claim_command))
    app.add_handler(CommandHandler("recognize", h.recognize_command))
    app.add_handler(CommandHandler("ping", h.ping_command))
    app.add_handler(CallbackQueryHandler(h.top_button_callback, pattern="^top_"))
    app.add_handler(CallbackQueryHandler(h.menu_category_callback, pattern="^menucat_"))
    app.add_handler(CallbackQueryHandler(h.menu_back_callback, pattern="^menu_back$"))

    # --------------------------------------------------------
    # MUSIC
    # --------------------------------------------------------
    app.add_handler(CommandHandler("play", h.play_command))

    # --------------------------------------------------------
    # MEDIA (image generation + photo/video search)
    # --------------------------------------------------------
    app.add_handler(CommandHandler("imagine", media.imagine_command))
    app.add_handler(CommandHandler("img", media.img_command))
    app.add_handler(CommandHandler("vid", media.vid_command))

    # --------------------------------------------------------
    # GAMES
    # --------------------------------------------------------
    app.add_handler(CommandHandler("trivia", h.trivia_command))
    app.add_handler(CallbackQueryHandler(h.trivia_callback, pattern="^trivia_"))
    app.add_handler(CommandHandler("grid", h.grid_command))
    app.add_handler(CommandHandler("rps", h.rps_command))
    app.add_handler(CommandHandler("coinflip", h.coinflip_command))
    app.add_handler(CommandHandler("dice", h.dice_command))
    app.add_handler(CommandHandler("slots", h.slots_command))
    app.add_handler(CommandHandler("truth", h.truth_command))
    app.add_handler(CommandHandler("dare", h.dare_command))
    app.add_handler(CommandHandler("gamble", h.gamble_command))
    app.add_handler(CommandHandler("steal", h.steal_command))
    app.add_handler(CommandHandler("duel", h.duel_command))

    # --------------------------------------------------------
    # ADMIN
    # --------------------------------------------------------
    app.add_handler(CommandHandler("badge", h.badge_command))
    app.add_handler(CommandHandler("promote", h.promote_command))
    app.add_handler(CommandHandler("demote", h.demote_command))
    app.add_handler(CommandHandler("antispam", h.antispam_command))
    app.add_handler(CommandHandler("poll", h.poll_command))
    app.add_handler(CommandHandler("givexp", h.givexp_command))
    app.add_handler(CommandHandler("warn", h.warn_command))
    app.add_handler(CommandHandler("warnings", h.warnings_command))
    app.add_handler(CommandHandler("clearwarns", h.clearwarns_command))
    app.add_handler(CommandHandler("mute", h.mute_command))
    app.add_handler(CommandHandler("unmute", h.unmute_command))
    app.add_handler(CommandHandler("kick", h.kick_command))
    app.add_handler(CommandHandler("ban", h.ban_command))

    # Owner-only — see OWNER_IDS at the top of handlers_admin.py.
    # Reply to any message with /broadcast to copy it into every
    # group the bot is in, or use /broadcast <text> directly.
    app.add_handler(CommandHandler("broadcast", h.broadcast_command))

    # --------------------------------------------------------
    # PASSIVE HANDLERS
    # (order matters: these run for every incoming text/voice/
    # sticker message that isn't a command above)
    # --------------------------------------------------------

    # Text messages -> AI chat, trivia answers, grid answers,
    # bare-word "menu"/"grid"/"trivia", and gift claims
    # (chat_with_ai_and_track internally checks all of these first)
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            h.chat_with_ai_and_track,
        )
    )

    # Voice notes -> transcribe + AI reply + TTS voice reply
    app.add_handler(
        MessageHandler(filters.VOICE, h.voice_message_handler)
    )

    # Stickers -> reply with a random sticker from the same pack
    app.add_handler(
        MessageHandler(filters.Sticker.ALL, h.sticker_reply_handler)
    )

    # --------------------------------------------------------
    # RUN
    # --------------------------------------------------------
    logger.info("BLOODY MD is starting with concurrent_updates=True...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()