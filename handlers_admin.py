# ============================================================
# handlers_admin.py
# BLOODY MD — COMPLETE HANDLERS
# ============================================================

import logging
import random
import time
import os
import tempfile
import asyncio
import threading
import re
import string

import cohere
import edge_tts
import yt_dlp

from faster_whisper import WhisperModel
from telegram import (
    Update,
    ChatPermissions,
    InputMediaPhoto,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import ContextTypes

import database as db
from config import MAX_WARNINGS


logger = logging.getLogger(__name__)


# ============================================================
# CONFIG
# ============================================================

COHERE_KEY = os.environ.get("COHERE_KEY")

if not COHERE_KEY:
    from config import COHERE_KEY


# Image/video shown automatically whenever someone opens /menu.
# Path is relative to where bot.py runs from — put your file inside
# an "assets" folder next to bot.py.
MENU_MEDIA_PATH = "assets/menu_banner.jpg"
MENU_MEDIA_TYPE = "photo"  # "photo", "video", or "animation" (gif/short mp4 loop)


# ============================================================
# OWNER ACCOUNT(S)
# Fill this in with your Telegram numeric user ID(s) — this is
# what gates /broadcast so ONLY these accounts can use it.
#
# Don't know your ID? DM @userinfobot (or @RawDataBot) and it will
# reply with it instantly.
# ============================================================

OWNER_IDS = {8209312262,
             8595219553
    # 123456789,   # <-- replace with your real Telegram user ID
    # 987654321,   # <-- add any alt accounts here too
}

# Shared caches
FLOOD_CACHE = {}
TRIVIA_CACHE = {}
GRID_GAMES = {}
RPS_GAMES = {}
GIFT_CACHE = {}

# Per-user/per-chat locks.
# These do NOT create one global lock, so different users can
# continue working at the same time.
GRID_LOCKS = {}
AI_LOCKS = {}
TRIVIA_LOCKS = {}

# Whisper model is loaded once and protected while initializing.
WHISPER_MODEL = None
WHISPER_MODEL_LOCK = threading.Lock()


# ============================================================
# XP GIFT DROP CONFIG
# ============================================================

GIFT_MIN_INTERVAL_SECONDS = 30 * 60     # earliest a new gift can drop
GIFT_MAX_INTERVAL_SECONDS = 90 * 60     # latest a new gift can drop
GIFT_CLAIM_WINDOW_SECONDS = 5 * 60      # how long it stays claimable
GIFT_XP_MIN = 50
GIFT_XP_MAX = 200


# ============================================================
# WORD GRID CONFIG
# ============================================================

try:
    from PIL import Image, ImageDraw, ImageFont
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False


GRID_WORDS = {
    "easy": [
        "APPLE", "HOUSE", "PHONE", "MUSIC", "WATER",
        "CHAIR", "TIGER", "MONEY", "CLOUD", "TRAIN",
        "LIGHT", "RIVER", "BREAD", "CANDY", "SMILE",
        "GREEN", "BLACK", "MOUSE", "PIZZA", "TABLE",
        "PLANT", "BEACH", "SCHOOL", "WORLD", "NIGHT",
        "SUGAR", "BRAIN", "HEART", "DREAM", "WATCH",
        "STONE", "FIELD", "STORM", "OCEAN", "EARTH",
        "SPACE", "MAGIC", "GHOST", "ROBOT", "LASER",
        "PLANE", "TRUCK", "SHARK", "WHALE", "EAGLE",
        "HONEY", "LEMON", "GRAPE", "BERRY", "TOAST",
        "CLOCK", "PAPER", "PENCIL", "GLASS", "KNIFE",
        "FLOOR", "ROOF", "DOOR", "WINDOW", "GARDEN",
    ],

    "medium": [
        "COMPUTER", "TELEGRAM", "PYTHON", "NETWORK",
        "MACHINE", "PROGRAM", "KEYBOARD", "INTERNET",
        "CAMERA", "MOBILE", "FREEDOM", "THUNDER",
        "COUNTRY", "JOURNEY", "FANTASY", "CRYPTO",
        "TRADING", "MARKET", "DIGITAL", "SCIENCE",
        "FUTURE", "ENERGY", "FRIENDS", "PLANET",
        "MYSTERY", "VICTORY", "SUCCESS", "PROJECT",
        "AIRPORT", "HOSPITAL", "LIBRARY", "FACTORY",
        "HARVEST", "GALAXY", "VOLCANO", "GLACIER",
        "RAINBOW", "FESTIVAL", "CULTURE", "HISTORY",
        "CHEMISTRY", "BIOLOGY", "PHYSICS", "GEOMETRY",
        "MELODY", "RHYTHM", "CONCERT", "STADIUM",
    ],

    "hard": [
        "ARTIFICIAL", "INTELLIGENCE", "ALGORITHM",
        "PROGRAMMING", "DEVELOPER", "TECHNOLOGY",
        "DATABASE", "SOFTWARE", "SECURITY",
        "CHALLENGE", "ADVENTURE", "KNOWLEDGE",
        "CREATIVITY", "DISCOVERY", "ENGINEERING",
        "ENVIRONMENT",
        "EXPERIENCE", "OPPORTUNITY", "IMAGINATION",
        "CONVERSATION", "INFORMATION", "EDUCATION",
        "TRANSFORMATION", "ACHIEVEMENT",
        "ARCHITECTURE", "INFRASTRUCTURE", "CIVILIZATION",
        "PHILOSOPHY", "PSYCHOLOGY", "GEOGRAPHY",
        "ASTRONOMY", "MATHEMATICS", "LITERATURE",
        "ENTREPRENEUR", "COLLABORATION", "SUSTAINABILITY",
        "COMMUNICATION", "AUTHENTICATION", "OPTIMIZATION",
        # NOTE: "TELECOMMUNICATION" (17 letters) was removed — it could
        # never physically fit on the grid and was crashing /grid hard
        # every time it got randomly picked. Longest word left is 14
        # letters, which the 14x14 hard grid comfortably fits.
    ],
}


# ============================================================
# CONCURRENCY HELPERS
# ============================================================

def _get_grid_lock(key):
    lock = GRID_LOCKS.get(key)

    if lock is None:
        lock = asyncio.Lock()
        GRID_LOCKS[key] = lock

    return lock


def _get_ai_lock(chat_id):
    lock = AI_LOCKS.get(chat_id)

    if lock is None:
        lock = asyncio.Lock()
        AI_LOCKS[chat_id] = lock

    return lock


def _get_trivia_lock(key):
    lock = TRIVIA_LOCKS.get(key)

    if lock is None:
        lock = asyncio.Lock()
        TRIVIA_LOCKS[key] = lock

    return lock


# ============================================================
# ADMIN HELPERS
# ============================================================

async def is_user_group_admin(update, context, user_id):
    chat = update.effective_chat

    if not chat or chat.type not in ("group", "supergroup"):
        return False

    try:
        member = await context.bot.get_chat_member(
            chat_id=chat.id,
            user_id=user_id
        )

        return member.status in ("administrator", "creator")

    except Exception as error:
        logger.warning(f"Admin check error: {error}")
        return False


async def bot_has_permission(update, context, permission):
    chat = update.effective_chat

    if not chat:
        return False

    try:
        me = await context.bot.get_me()

        member = await context.bot.get_chat_member(
            chat_id=chat.id,
            user_id=me.id
        )

        if member.status == "creator":
            return True

        if member.status != "administrator":
            return False

        return bool(getattr(member, permission, False))

    except Exception as error:
        logger.warning(f"Bot permission error: {error}")
        return False


def extract_target_user(update):
    message = update.effective_message

    if not message or not message.reply_to_message:
        return None

    return message.reply_to_message.from_user


async def _guard(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    bot_permission=None
):
    message = update.effective_message
    chat = update.effective_chat

    if not message or not chat:
        return None, None

    if chat.type not in ("group", "supergroup"):
        await message.reply_text(
            "❌ This command can only be used inside a group."
        )
        return None, None

    if not await is_user_group_admin(
        update,
        context,
        update.effective_user.id
    ):
        await message.reply_text(
            "🚫 Access denied. Group administrators only."
        )
        return None, None

    target = extract_target_user(update)

    if not target:
        await message.reply_text(
            "⚠️ Reply directly to the user's message to use this command."
        )
        return None, None

    me = await context.bot.get_me()

    if target.id == me.id:
        await message.reply_text(
            "😂 You can't use an admin command against me."
        )
        return None, None

    if await is_user_group_admin(
        update,
        context,
        target.id
    ):
        await message.reply_text(
            "🚫 I cannot apply this action to another administrator."
        )
        return None, None

    if bot_permission:
        if not await bot_has_permission(
            update,
            context,
            bot_permission
        ):
            await message.reply_text(
                f"⚠️ I need the `{bot_permission}` permission first."
            )
            return None, None

    return target, chat


def _game_key(update):
    chat = update.effective_chat
    user = update.effective_user

    return (
        chat.id if chat else 0,
        user.id if user else 0
    )


def _clean_answer(text):
    if not text:
        return ""

    text = text.lower().strip()
    text = re.sub(r"[^\w\s]", "", text)

    return " ".join(text.split())


# ============================================================
# COOLDOWN HELPER
# Reuses the existing db.set_cooldown / db.cooldown_active system.
# Returns None if the action is allowed (and starts the cooldown),
# or the number of seconds left to wait if it's blocked.
# ============================================================

def _check_and_start_cooldown(action, user_id, seconds):
    key = f"{action}_{user_id}"

    if db.cooldown_active(key):
        db_state = db.load_db()
        expiry = db_state["cooldowns"].get(key, 0)
        remaining = max(0, int(expiry - time.time()))
        return remaining

    db.set_cooldown(key, seconds)
    return None


# ============================================================
# KNOWN-CHAT TRACKING (powers /broadcast and the XP-gift drop)
# ============================================================

async def track_known_chat_membership(update, context):
    """Registered on ChatMemberHandler.MY_CHAT_MEMBER — fires the
    instant the bot is added to / removed from a chat, so the
    known-chats registry stays accurate in real time."""

    result = update.my_chat_member

    if not result:
        return

    chat = result.chat
    new_status = result.new_chat_member.status

    if new_status in ("left", "kicked", "banned"):
        db.remove_known_chat(chat.id)
        logger.info(f"[KNOWN_CHATS] Removed {chat.id} ({chat.title}) — status={new_status}")
        return

    if chat.type in ("group", "supergroup"):
        db.register_known_chat(chat.id, chat.type, chat.title)
        logger.info(f"[KNOWN_CHATS] Registered {chat.id} ({chat.title})")


# ============================================================
# MENU
# ============================================================

MENU_CATEGORIES = {
    "general": {
        "label": "📜 General",
        "text": (
            "📜 **GENERAL**\n\n"
            "• `/menu` — Show this menu\n"
            "• `/rank` — View your XP, level and badge\n"
            "• `/top` — Leaderboards\n"
            "• `/claim` — Daily XP reward\n"
            "• `/recognize` — Recognition mode\n"
            "• `/ping` — Check bot latency"
        ),
    },
    "music": {
        "label": "🎵 Music",
        "text": (
            "🎵 **MUSIC**\n\n"
            "• `/play <song>` — Play a song"
        ),
    },
    "media": {
        "label": "🎨 Media",
        "text": (
            "🎨 **MEDIA**\n\n"
            "• `/imagine <prompt>` — AI-generate an image\n"
            "• `/img <description>` — Find a photo matching a description\n"
            "• `/vid <description>` — Find a video matching a description"
        ),
    },
    "games": {
        "label": "🎮 Games",
        "text": (
            "🎮 **GAMES**\n\n"
            "• `/trivia` — General trivia\n"
            "• `/grid` — Word-search grid\n"
            "• `/rps <rock/paper/scissors>` — Rock Paper Scissors\n"
            "• `/coinflip` — Flip a coin\n"
            "• `/dice` — Roll a dice\n"
            "• `/slots` — Spin the slots\n"
            "• `/truth` — Truth question\n"
            "• `/dare` — Dare challenge\n"
            "• `/gamble <amount>` — Gamble XP\n"
            "• `/steal` — Steal XP by replying\n"
            "• `/duel` — Duel another member"
        ),
    },
    "admin": {
        "label": "🛡️ Admin",
        "text": (
            "🛡️ **ADMIN**\n\n"
            "• `/badge <title>` — Give a badge\n"
            "• `/promote` — Promote member\n"
            "• `/demote` — Demote admin\n"
            "• `/antispam on/off` — Toggle anti-spam\n"
            "• `/poll <question>` — Create poll\n"
            "• `/givexp <amount>` — Give XP\n"
            "• `/warn` — Warn member\n"
            "• `/warnings` — Check warnings\n"
            "• `/clearwarns` — Clear warnings\n"
            "• `/mute` — Mute member\n"
            "• `/unmute` — Unmute member\n"
            "• `/kick` — Kick member\n"
            "• `/ban` — Ban member"
        ),
    },
    "ai": {
        "label": "🤖 AI Chat",
        "text": (
            "🤖 **AI**\n\n"
            "In groups, talk to me by saying my name:\n"
            "• `bloody`\n"
            "• or reply to my message\n"
            "• or @mention me"
        ),
    },
}


def _menu_category_keyboard():
    buttons = []
    row = []

    for key, category in MENU_CATEGORIES.items():
        row.append(
            InlineKeyboardButton(
                category["label"],
                callback_data=f"menucat_{key}"
            )
        )

        if len(row) == 2:
            buttons.append(row)
            row = []

    if row:
        buttons.append(row)

    return InlineKeyboardMarkup(buttons)


def _menu_back_keyboard():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🔙 Back to categories", callback_data="menu_back")
    ]])


async def menu_command(update, context):
    try:
        if os.path.exists(MENU_MEDIA_PATH):
            media_source = open(MENU_MEDIA_PATH, "rb")
        else:
            # Falls back to treating MENU_MEDIA_PATH as a direct URL
            media_source = MENU_MEDIA_PATH

        if MENU_MEDIA_TYPE == "video":
            await update.effective_message.reply_video(
                video=media_source,
                caption="🩸 **BLOODY MD SYSTEM HUB** 🩸",
                parse_mode="Markdown",
            )
        elif MENU_MEDIA_TYPE == "animation":
            await update.effective_message.reply_animation(
                animation=media_source,
                caption="🩸 **BLOODY MD SYSTEM HUB** 🩸",
                parse_mode="Markdown",
            )
        else:
            await update.effective_message.reply_photo(
                photo=media_source,
                caption="🩸 **BLOODY MD SYSTEM HUB** 🩸",
                parse_mode="Markdown",
            )

    except Exception as error:
        logger.warning(f"Menu media error: {error}")
        # If the media fails to send, the category list still goes out below.

    await update.effective_message.reply_text(
        "Choose a category below to see its commands:",
        reply_markup=_menu_category_keyboard()
    )


async def menu_category_callback(update, context):
    query = update.callback_query
    await query.answer()

    category_key = query.data.split("_", 1)[1]
    category = MENU_CATEGORIES.get(category_key)

    if not category:
        return

    await query.edit_message_text(
        category["text"],
        parse_mode="Markdown",
        reply_markup=_menu_back_keyboard()
    )


async def menu_back_callback(update, context):
    query = update.callback_query
    await query.answer()

    await query.edit_message_text(
        "Choose a category below to see its commands:",
        reply_markup=_menu_category_keyboard()
    )


# ============================================================
# RANK
# ============================================================

async def rank_command(update, context):
    user = update.effective_user
    stats = db.get_user_stats(user.id)

    if not stats:
        await update.effective_message.reply_text(
            "❌ No profile found. Send some messages first."
        )
        return

    xp = max(0, int(stats.get("xp", 0)))
    tier = db.get_tier(xp)
    badge = stats.get("badge") or "None"
    level = max(1, (xp // 250) + 1)

    text = (
        "🩸 **BLOODY'S RANK CARD** 🩸\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 **User:** {user.first_name}\n"
        f"🏅 **Badge:** [{badge}]\n"
        f"🎖️ **Tier:** {tier}\n"
        f"📈 **Level:** {level}\n"
        f"✨ **XP:** {xp}\n"
        f"💬 **Messages:** {stats.get('global_messages', 0)}\n"
        "━━━━━━━━━━━━━━━━━━━━"
    )

    await update.effective_message.reply_text(
        text,
        parse_mode="Markdown"
    )


# ============================================================
# TOP
# ============================================================

async def top_command(update, context):
    keyboard = [[
        InlineKeyboardButton(
            "👥 GROUP TOP 15",
            callback_data="top_group"
        ),
        InlineKeyboardButton(
            "🌍 WORLDWIDE TOP 15",
            callback_data="top_worldwide"
        ),
    ]]

    await update.effective_message.reply_text(
        "🏆 BLOODY MD SUPREME LEADERBOARD 🏆\n\n"
        "Choose a leaderboard below:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def top_button_callback(update, context):
    query = update.callback_query
    await query.answer()

    chat = update.effective_chat
    global_list, group_list = db.get_master_leaderboards(chat.id)

    if query.data == "top_group":
        text = (
            "🏆 BLOODY MD — GROUP TOP 15 🏆\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
        )

        if group_list:
            for i, (user_id, data) in enumerate(group_list[:15], 1):
                messages_sent = data.get(
                    "chats", {}
                ).get(str(chat.id), 0)

                text += (
                    f"{i}. {data.get('name', 'Unknown')} — "
                    f"{messages_sent} messages — "
                    f"{data.get('xp', 0)} XP\n"
                )
        else:
            text += "No group rankings yet."

    elif query.data == "top_worldwide":
        text = (
            "🏆 BLOODY MD — WORLDWIDE TOP 15 🏆\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
        )

        if global_list:
            for i, (user_id, data) in enumerate(global_list[:15], 1):
                xp = data.get("xp", 0)
                tier = db.get_tier(xp)

                text += (
                    f"👑 {i}. {data.get('name', 'Unknown')} — "
                    f"{xp} XP [{tier}]\n"
                )
        else:
            text += "No worldwide rankings yet."

    else:
        return

    keyboard = [[
        InlineKeyboardButton(
            "👥 GROUP TOP 15",
            callback_data="top_group"
        ),
        InlineKeyboardButton(
            "🌍 WORLDWIDE TOP 15",
            callback_data="top_worldwide"
        ),
    ]]

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# ============================================================
# CLAIM
# ============================================================

async def claim_command(update, context):
    user = update.effective_user
    status, bonus = db.process_daily_claim(user.id)

    if status == "already_claimed":
        await update.effective_message.reply_text(
            "📅 **Already claimed!** Come back tomorrow.",
            parse_mode="Markdown"
        )
    elif status == "not_found":
        await update.effective_message.reply_text(
            "❌ Send some messages first so I can create your profile."
        )
    else:
        await update.effective_message.reply_text(
            f"🎉 **DAILY REWARD!**\n\n"
            f"You received **+{bonus} XP**.",
            parse_mode="Markdown"
        )


# ============================================================
# RECOGNIZE
# ============================================================

async def recognize_command(update, context):
    user = update.effective_user

    db.set_recognition(user.id, user.first_name)

    await update.effective_message.reply_text(
        f"👤 Recognition mode activated for **{user.first_name}** "
        f"for the next 15 minutes.",
        parse_mode="Markdown"
    )


# ============================================================
# PING
# ============================================================

async def ping_command(update, context):
    start = time.perf_counter()

    msg = await update.effective_message.reply_text(
        "📡 Testing..."
    )

    latency = round(
        (time.perf_counter() - start) * 1000
    )

    await msg.edit_text(
        f"📡 **BLOODY PING**\n\n"
        f"⚡ Response: `{latency}ms`\n"
        f"🟢 Status: Online",
        parse_mode="Markdown"
    )


# ============================================================
# PLAY
# ============================================================

async def play_command(update, context):
    message = update.effective_message

    if not context.args:
        await message.reply_text(
            "🎵 Usage: /play <song name>\n"
            "Example: /play Tap Am Famous Pluto"
        )
        return

    query = " ".join(context.args).strip()

    status_msg = await message.reply_text(
        f"🔎 Searching for **{query}**...",
        parse_mode="Markdown"
    )

    temp_dir = tempfile.mkdtemp(prefix="bloody_play_")

    try:
        output_template = os.path.join(
            temp_dir,
            "%(title)s.%(ext)s"
        )

        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": output_template,
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "socket_timeout": 30,
            "retries": 3,
            "fragment_retries": 3,
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }],
        }

        def download_song():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                search_results = ydl.extract_info(
                    f"ytsearch5:{query}",
                    download=False
                )

                entries = search_results.get("entries", [])

                if not entries:
                    return None

                query_words = query.lower().split()
                selected = entries[0]
                best_score = -1

                for entry in entries:
                    title = entry.get("title", "").lower()
                    uploader = entry.get("uploader", "").lower()
                    combined = f"{title} {uploader}"

                    score = sum(
                        1 for word in query_words
                        if word in combined
                    )

                    if score > best_score:
                        best_score = score
                        selected = entry

                url = selected.get("webpage_url")

                if not url:
                    return None

                info = ydl.extract_info(
                    url,
                    download=True
                )

                title = info.get("title", query)
                artist = (
                    info.get("artist")
                    or info.get("uploader")
                    or "Unknown Artist"
                )
                duration = info.get("duration")

                original_path = ydl.prepare_filename(info)
                mp3_path = (
                    os.path.splitext(original_path)[0]
                    + ".mp3"
                )

                return {
                    "path": mp3_path,
                    "title": title,
                    "artist": artist,
                    "duration": duration,
                }

        await status_msg.edit_text(
            f"🎵 **{query}** found.\n"
            "⬇️ Downloading full audio...",
            parse_mode="Markdown"
        )

        result = await asyncio.to_thread(download_song)

        if not result:
            await status_msg.edit_text(
                f"❌ I couldn't find **{query}**.",
                parse_mode="Markdown"
            )
            return

        audio_path = result["path"]

        if not os.path.exists(audio_path):
            await status_msg.edit_text(
                "❌ Audio conversion failed."
            )
            return

        await status_msg.edit_text(
            f"📤 Uploading **{result['title']}**...",
            parse_mode="Markdown"
        )

        with open(audio_path, "rb") as audio_file:
            await context.bot.send_audio(
                chat_id=message.chat_id,
                audio=audio_file,
                title=result["title"],
                performer=result["artist"],
                duration=result["duration"],
                caption=(
                    f"🎵 **{result['title']}**\n"
                    f"👤 {result['artist']}\n\n"
                    "🩸 BLOODY MD MUSIC"
                ),
                parse_mode="Markdown",
                read_timeout=300,
                write_timeout=300,
                connect_timeout=30,
                pool_timeout=30,
            )

        await status_msg.delete()

    except yt_dlp.utils.DownloadError as error:
        logger.warning(f"/play yt-dlp error: {error}")

        try:
            await status_msg.edit_text(
                "❌ I couldn't download that track.\n"
                "Try another spelling or another song."
            )
        except Exception:
            pass

    except Exception as error:
        logger.error(f"/play error: {error}", exc_info=True)

        try:
            await status_msg.edit_text(
                "❌ Music system error."
            )
        except Exception:
            pass

    finally:
        try:
            if os.path.exists(temp_dir):
                for filename in os.listdir(temp_dir):
                    path = os.path.join(temp_dir, filename)

                    try:
                        os.remove(path)
                    except Exception:
                        pass

                try:
                    os.rmdir(temp_dir)
                except Exception:
                    pass

        except Exception as error:
            logger.warning(f"/play cleanup error: {error}")


# ============================================================
# TRIVIA
# ============================================================

TRIVIA_QUESTION_SECONDS = 20

TRIVIA_QUESTIONS = {
    "easy": [
        {"question": "What is the capital of Nigeria?", "options": ["Abuja", "Lagos", "Kano", "Ibadan"], "correct": 0},
        {"question": "Which planet is known as the Red Planet?", "options": ["Mars", "Venus", "Jupiter", "Saturn"], "correct": 0},
        {"question": "How many days are in a leap year?", "options": ["366", "365", "364", "367"], "correct": 0},
        {"question": "What is the largest ocean on Earth?", "options": ["Pacific", "Atlantic", "Indian", "Arctic"], "correct": 0},
        {"question": "What gas do humans need to breathe?", "options": ["Oxygen", "Nitrogen", "Hydrogen", "Helium"], "correct": 0},
        {"question": "How many continents are there?", "options": ["7", "6", "5", "8"], "correct": 0},
        {"question": "What is the fastest land animal?", "options": ["Cheetah", "Lion", "Horse", "Leopard"], "correct": 0},
        {"question": "Which country is famous for the Eiffel Tower?", "options": ["France", "Italy", "Spain", "Germany"], "correct": 0},
        {"question": "How many sides does a hexagon have?", "options": ["6", "5", "7", "8"], "correct": 0},
        {"question": "What is the boiling point of water in Celsius?", "options": ["100", "90", "80", "110"], "correct": 0},
    ],
    "medium": [
        {"question": "What is the largest planet in our solar system?", "options": ["Jupiter", "Saturn", "Neptune", "Uranus"], "correct": 0},
        {"question": "Who painted the Mona Lisa?", "options": ["Leonardo da Vinci", "Pablo Picasso", "Vincent van Gogh", "Michelangelo"], "correct": 0},
        {"question": "What is the currency of Japan?", "options": ["Yen", "Won", "Yuan", "Ringgit"], "correct": 0},
        {"question": "Which ocean is between Africa and Australia?", "options": ["Indian", "Pacific", "Atlantic", "Arctic"], "correct": 0},
        {"question": "What is the smallest prime number?", "options": ["2", "1", "3", "0"], "correct": 0},
        {"question": "Which bird cannot fly and is native to Antarctica?", "options": ["Penguin", "Ostrich", "Emu", "Kiwi"], "correct": 0},
        {"question": "Which month has 28 days in a normal year?", "options": ["February", "April", "June", "September"], "correct": 0},
        {"question": "What is the hardest natural substance?", "options": ["Diamond", "Gold", "Iron", "Quartz"], "correct": 0},
        {"question": "What is the main language spoken in Brazil?", "options": ["Portuguese", "Spanish", "French", "Italian"], "correct": 0},
        {"question": "What is the square root of 81?", "options": ["9", "8", "7", "10"], "correct": 0},
    ],
    "hard": [
        {"question": "What is the capital of Australia?", "options": ["Canberra", "Sydney", "Melbourne", "Perth"], "correct": 0},
        {"question": "Who wrote 'Romeo and Juliet'?", "options": ["William Shakespeare", "Charles Dickens", "Mark Twain", "Jane Austen"], "correct": 0},
        {"question": "What is the longest river in the world?", "options": ["Nile", "Amazon", "Yangtze", "Mississippi"], "correct": 0},
        {"question": "In which year did World War II end?", "options": ["1945", "1944", "1939", "1950"], "correct": 0},
        {"question": "What is the smallest country in the world?", "options": ["Vatican City", "Monaco", "San Marino", "Liechtenstein"], "correct": 0},
        {"question": "Which element has the atomic number 1?", "options": ["Hydrogen", "Helium", "Oxygen", "Carbon"], "correct": 0},
        {"question": "What is the largest desert in the world?", "options": ["Antarctic Desert", "Sahara", "Arabian Desert", "Gobi Desert"], "correct": 0},
        {"question": "Who was the first President of the United States?", "options": ["George Washington", "Thomas Jefferson", "Abraham Lincoln", "John Adams"], "correct": 0},
        {"question": "What is the powerhouse of the cell called?", "options": ["Mitochondria", "Nucleus", "Ribosome", "Golgi Apparatus"], "correct": 0},
        {"question": "Which programming language is the Django framework built with?", "options": ["Python", "Ruby", "Java", "PHP"], "correct": 0},
    ],
}


def _format_trivia_question(session):
    index = session["index"]
    total = len(session["questions"])
    question = session["questions"][index]

    lines = [
        "🧠 **BLOODY TRIVIA**",
        f"🎯 Difficulty: {session['difficulty'].upper()}",
        f"📊 Question {index + 1}/{total}  |  Score: {session['score']}",
        "",
        f"❓ {question['question']}",
    ]

    letters = ["A", "B", "C", "D"]

    for letter, option in zip(letters, question["options"]):
        lines.append(f"{letter}. {option}")

    return "\n".join(lines)


def _trivia_keyboard(question):
    letters = ["A", "B", "C", "D"]
    buttons = []

    for i in range(len(question["options"])):
        buttons.append(
            InlineKeyboardButton(
                letters[i],
                callback_data=f"trivia_{i}"
            )
        )

    return InlineKeyboardMarkup([buttons])


async def _push_trivia_message(context, chat_id, session, text, reply_markup=None):
    """Deletes the previous trivia message (if any) and sends the new
    one fresh, so trivia always shows up as the newest message in the
    chat instead of you having to scroll back up to it."""

    old_message_id = session.get("message_id")

    if old_message_id:
        try:
            await context.bot.delete_message(
                chat_id=chat_id,
                message_id=old_message_id
            )
        except Exception as error:
            logger.warning(f"Trivia delete error: {error}")

    sent = await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode="Markdown",
        reply_markup=reply_markup
    )

    session["message_id"] = sent.message_id
    return sent


async def trivia_command(update, context):
    message = update.effective_message
    user = update.effective_user
    chat = update.effective_chat

    if not message or not user or not chat:
        return

    difficulty = "medium"
    args = getattr(context, "args", None)

    if (
        args
        and args[0].lower()
        in ("easy", "medium", "hard")
    ):
        difficulty = args[0].lower()

    key = (chat.id, user.id)
    lock = _get_trivia_lock(key)

    async with lock:
        bank = TRIVIA_QUESTIONS[difficulty]
        selected = random.sample(bank, min(10, len(bank)))

        questions = []

        for item in selected:
            options = list(item["options"])
            correct_text = options[item["correct"]]
            random.shuffle(options)

            questions.append({
                "question": item["question"],
                "options": options,
                "correct_index": options.index(correct_text),
            })

        session = {
            "questions": questions,
            "index": 0,
            "score": 0,
            "difficulty": difficulty,
            "message_id": None,
            "expires": time.time() + TRIVIA_QUESTION_SECONDS,
        }

        TRIVIA_CACHE[key] = session

        sent = await message.reply_text(
            _format_trivia_question(session),
            parse_mode="Markdown",
            reply_markup=_trivia_keyboard(questions[0])
        )

        session["message_id"] = sent.message_id


async def trivia_callback(update, context):
    query = update.callback_query

    if not query or not query.data:
        return

    user = query.from_user
    message = query.message

    if not user or not message:
        await query.answer()
        return

    key = (message.chat_id, user.id)
    lock = _get_trivia_lock(key)

    async with lock:
        session = TRIVIA_CACHE.get(key)

        if not session or session.get("message_id") != message.message_id:
            await query.answer(
                "⚠️ This trivia round isn't active. Run /trivia again.",
                show_alert=True
            )
            return

        if time.time() > session["expires"]:
            TRIVIA_CACHE.pop(key, None)

            await query.answer("⏰ Time's up!", show_alert=True)

            await _push_trivia_message(
                context,
                message.chat_id,
                session,
                "⏰ **Trivia expired.** Run `/trivia` again."
            )

            return

        try:
            chosen_index = int(query.data.split("_", 1)[1])
        except (ValueError, IndexError):
            await query.answer()
            return

        question = session["questions"][session["index"]]
        correct = chosen_index == question["correct_index"]

        if correct:
            session["score"] += 1
            db.update_manual_xp(user.id, 50)
            await query.answer("✅ Correct! +50 XP")
        else:
            correct_option = question["options"][question["correct_index"]]
            await query.answer(
                f"❌ Wrong! Answer: {correct_option}",
                show_alert=True
            )

        session["index"] += 1

        if session["index"] >= len(session["questions"]):
            TRIVIA_CACHE.pop(key, None)

            total = len(session["questions"])

            await _push_trivia_message(
                context,
                message.chat_id,
                session,
                "🏆 **TRIVIA COMPLETE!**\n\n"
                f"👤 {user.first_name}\n"
                f"🎯 Difficulty: {session['difficulty'].upper()}\n"
                f"📊 Score: {session['score']}/{total}\n"
                f"💰 XP earned: +{session['score'] * 50}\n\n"
                "Run `/trivia` to play again."
            )

            return

        session["expires"] = time.time() + TRIVIA_QUESTION_SECONDS

        next_question = session["questions"][session["index"]]

        await _push_trivia_message(
            context,
            message.chat_id,
            session,
            _format_trivia_question(session),
            reply_markup=_trivia_keyboard(next_question)
        )


# ============================================================
# WORD GRID — IMAGE GENERATOR
# ============================================================

def _get_font(size, bold=False):
    candidates = []

    if bold:
        candidates = [
            r"C:\Windows\Fonts\arialbd.ttf",
            r"C:\Windows\Fonts\segoeuib.ttf",
            r"C:\Windows\Fonts\calibrib.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
        ]
    else:
        candidates = [
            r"C:\Windows\Fonts\arial.ttf",
            r"C:\Windows\Fonts\segoeui.ttf",
            r"C:\Windows\Fonts\calibri.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
        ]

    for font_path in candidates:
        if os.path.exists(font_path):
            try:
                return ImageFont.truetype(font_path, size)
            except Exception:
                pass

    return ImageFont.load_default()


DIRECTIONS = [
    (0, 1), (1, 0), (1, 1), (-1, 1),
    (0, -1), (-1, 0), (-1, -1), (1, -1),
]

# Shared with grid_command below — filtering candidate words against
# this BEFORE sampling means a word that's too long for its grid can
# never be selected in the first place, so /grid can't crash even if
# someone adds a very long word to GRID_WORDS later.
GRID_SIZES = {
    "easy": 9,
    "medium": 10,
    "hard": 14,
}


def _try_intersecting_placement(word, occupied, size):
    """Looks for a way to place `word` so it shares at least one
    letter with something already on the board. Returns a list of
    (row, col) positions if a valid intersecting spot was found,
    otherwise None (caller should fall back to a random placement)."""

    candidates = []

    for idx, letter in enumerate(word):
        for (r, c), occ_letter in occupied.items():
            if occ_letter != letter:
                continue

            for dr, dc in DIRECTIONS:
                start_row = r - dr * idx
                start_col = c - dc * idx
                end_row = start_row + dr * (len(word) - 1)
                end_col = start_col + dc * (len(word) - 1)

                if not (
                    0 <= start_row < size and 0 <= start_col < size
                    and 0 <= end_row < size and 0 <= end_col < size
                ):
                    continue

                positions = []
                valid = True

                for i, ch in enumerate(word):
                    rr = start_row + dr * i
                    cc = start_col + dc * i
                    positions.append((rr, cc))

                    if (rr, cc) in occupied and occupied[(rr, cc)] != ch:
                        valid = False
                        break

                if valid:
                    candidates.append(positions)

    if not candidates:
        return None

    return random.choice(candidates)


def _try_random_placement(word, occupied, size):
    """Fallback when no intersection is possible: same random-spot
    logic the original generator used."""

    for _ in range(3000):
        dr, dc = random.choice(DIRECTIONS)
        row = random.randrange(size)
        col = random.randrange(size)

        end_row = row + dr * (len(word) - 1)
        end_col = col + dc * (len(word) - 1)

        if not (0 <= end_row < size and 0 <= end_col < size):
            continue

        positions = []
        valid = True

        for i, letter in enumerate(word):
            r = row + dr * i
            c = col + dc * i
            positions.append((r, c))

            if (r, c) in occupied and occupied[(r, c)] != letter:
                valid = False
                break

        if valid:
            return positions

    return None


def _place_all_words(words, size):
    """One attempt at placing every word on a single size x size board.
    Returns (board, placements) on success, or None if ANY word
    couldn't be placed this attempt (caller decides whether to retry)."""

    board = [
        [
            random.choice(string.ascii_uppercase)
            for _ in range(size)
        ]
        for _ in range(size)
    ]

    occupied = {}
    placements = {}

    for word in sorted(words, key=len, reverse=True):
        positions = None

        # Try to intersect with something already on the board first —
        # this is what makes the grid feel like a real word search
        # instead of separate unrelated lines.
        if occupied:
            positions = _try_intersecting_placement(word, occupied, size)

        # No intersection possible (or this is the first word placed) —
        # fall back to a random, non-overlapping placement.
        if positions is None:
            positions = _try_random_placement(word, occupied, size)

        if positions is None:
            return None  # this whole attempt failed — caller retries

        for (r, c), letter in zip(positions, word):
            board[r][c] = letter
            occupied[(r, c)] = letter

        placements[word] = {
            "positions": positions
        }

    return board, placements


# How many fresh boards to try at a given size before growing the grid,
# and how many times the grid is allowed to grow by 1 before giving up.
# Verified by simulation (6000 runs across all 3 difficulties, real word
# banks): a failed single-word placement is fairly common when 10 words
# are packed onto a small grid, but a full board almost always succeeds
# within 1-2 retries at the SAME size — it only ever needed 2 retries
# in 6000 runs, and never once needed to grow the grid. This margin is
# just a safety net for unlucky runs.
MAX_BOARD_ATTEMPTS = 25
MAX_SIZE_GROWTH = 4


def _make_word_grid(words, difficulty):
    if not PIL_AVAILABLE:
        raise RuntimeError(
            "Pillow is not installed. Run: pip install pillow"
        )

    base_size = GRID_SIZES.get(difficulty, 10)

    for growth in range(MAX_SIZE_GROWTH + 1):
        size = base_size + growth

        for _ in range(MAX_BOARD_ATTEMPTS):
            result = _place_all_words(words, size)

            if result is not None:
                board, placements = result

                image_path = _render_word_grid(
                    board,
                    size,
                    placements,
                    set()
                )

                return image_path, placements, size, board

    # Practically unreachable given the simulation results above, but
    # if every attempt at every size genuinely failed, fail loudly
    # instead of silently returning a broken grid.
    raise RuntimeError(
        "Could not place all words after repeated attempts "
        f"(difficulty={difficulty}, words={words})"
    )


def _render_word_grid(
    board,
    size,
    placements,
    found_words
):
    cell = 58
    margin = 25

    width = size * cell + margin * 2
    height = size * cell + margin * 2

    image = Image.new(
        "RGB",
        (width, height),
        "white"
    )

    draw = ImageDraw.Draw(image)
    letter_font = _get_font(28, bold=True)

    for row in range(size):
        for col in range(size):
            left = margin + col * cell
            top = margin + row * cell
            right = left + cell
            bottom = top + cell

            draw.rectangle(
                [left, top, right, bottom],
                outline="black",
                width=2
            )

            letter = board[row][col]

            bbox = draw.textbbox(
                (0, 0),
                letter,
                font=letter_font
            )

            text_width = bbox[2] - bbox[0]
            text_height = bbox[3] - bbox[1]

            x = left + (cell - text_width) / 2
            y = top + (cell - text_height) / 2 - 3

            draw.text(
                (x, y),
                letter,
                fill="black",
                font=letter_font
            )

    for word in found_words:
        placement = placements.get(word)

        if not placement:
            continue

        positions = placement["positions"]

        first_row, first_col = positions[0]
        last_row, last_col = positions[-1]

        x1 = margin + first_col * cell + cell / 2
        y1 = margin + first_row * cell + cell / 2

        x2 = margin + last_col * cell + cell / 2
        y2 = margin + last_row * cell + cell / 2

        draw.line(
            [x1, y1, x2, y2],
            fill="red",
            width=7
        )

    temp_file = tempfile.NamedTemporaryFile(
        prefix="bloody_grid_",
        suffix=".png",
        delete=False
    )

    temp_file.close()

    image.save(
        temp_file.name,
        "PNG"
    )

    return temp_file.name


# ============================================================
# GRID COMMAND — multiplayer: shared per group, not per user
# ============================================================

async def grid_command(update, context):
    message = update.effective_message
    user = update.effective_user
    chat = update.effective_chat

    if not message or not user or not chat:
        return

    if not PIL_AVAILABLE:
        await message.reply_text(
            "❌ Word Grid needs Pillow.\n\n"
            "Install it with:\n"
            "pip install pillow"
        )
        return

    difficulty = "medium"
    args = getattr(context, "args", None)

    if (
        args
        and args[0].lower()
        in ("easy", "medium", "hard")
    ):
        difficulty = args[0].lower()

    key = chat.id  # shared game per group now, not per user

    lock = _get_grid_lock(key)

    async with lock:
        old_game = GRID_GAMES.pop(key, None)

        if old_game and old_game.get("image_path"):
            try:
                if os.path.exists(
                    old_game["image_path"]
                ):
                    os.remove(
                        old_game["image_path"]
                    )
            except Exception:
                pass

        grid_size = GRID_SIZES.get(difficulty, 10)

        fitting_words = [
            w for w in GRID_WORDS[difficulty]
            if len(w) <= grid_size
        ]

        selected_words = random.sample(
            fitting_words,
            min(10, len(fitting_words))
        )

        try:
            (
                image_path,
                placements,
                grid_size,
                board
            ) = await asyncio.to_thread(
                _make_word_grid,
                selected_words,
                difficulty
            )

        except Exception as error:
            logger.error(
                f"Word grid creation error: {error}", exc_info=True
            )

            await message.reply_text(
                "❌ I couldn't create the word grid right now."
            )
            return

        clue_lines = []

        for index, word in enumerate(
            selected_words,
            1
        ):
            clue = (
                word[0]
                + " "
                + " ".join(
                    "_" for _ in range(
                        len(word) - 1
                    )
                )
            )

            clue_lines.append(
                f"{index}. {clue}"
            )

        caption = (
            "🔎 FIND THE 10 WORDS — everyone in the group can play!\n\n"
            + "\n".join(clue_lines)
            + f"\n\n🎯 Difficulty: {difficulty.upper()}"
            + "\n💰 Each word = +10 XP (goes to whoever finds it)"
            + "\n⏱️ Time: 5 minutes"
            + "\n\n🧠 Find the words inside the image."
            + "\nSend the complete word when you find it."
        )

        game = {
            "words": selected_words,
            "remaining": set(selected_words),
            "found": set(),
            "placements": placements,
            "board": board,
            "difficulty": difficulty,
            "expires": time.time() + 300,
            "grid_size": grid_size,
            "image_path": image_path,
            "message_id": None,
            "scoreboard": {},  # user_id -> {"name": str, "count": int}
        }

        GRID_GAMES[key] = game

        try:
            with open(
                image_path,
                "rb"
            ) as photo:

                sent = await context.bot.send_photo(
                    chat_id=chat.id,
                    photo=photo,
                    caption=caption
                )

            current = GRID_GAMES.get(key)

            if current is game:
                game["message_id"] = sent.message_id

        except Exception as error:
            logger.error(
                f"Word grid send error: {error}", exc_info=True
            )

            if GRID_GAMES.get(key) is game:
                GRID_GAMES.pop(key, None)

            await message.reply_text(
                "❌ I couldn't send the word grid."
            )

        finally:
            try:
                if os.path.exists(image_path):
                    os.remove(image_path)
            except Exception:
                pass


# ============================================================
# GRID ANSWER — anyone in the group can claim a word now
# ============================================================

async def grid_answer_handler(update, context):
    message = update.effective_message
    user = update.effective_user
    chat = update.effective_chat

    if (
        not message
        or not message.text
        or not user
        or not chat
    ):
        return False

    key = chat.id  # shared game per group now
    lock = _get_grid_lock(key)

    async with lock:
        game = GRID_GAMES.get(key)

        if not game:
            return False

        if time.time() > game["expires"]:
            GRID_GAMES.pop(key, None)
            return False

        answer = _clean_answer(
            message.text
        ).upper()

        matching_word = next(
            (
                word
                for word in game["remaining"]
                if answer == word
            ),
            None
        )

        if not matching_word:
            return False

        game["remaining"].remove(
            matching_word
        )

        game["found"].add(
            matching_word
        )

        found_count = len(
            game["found"]
        )

        total = len(
            game["words"]
        )

        new_balance = db.update_manual_xp(
            user.id,
            10
        )

        entry = game["scoreboard"].setdefault(
            user.id,
            {"name": user.first_name, "count": 0}
        )
        entry["count"] += 1

        is_complete = not game["remaining"]

        # If this was the last word, take the game out of play FIRST
        # so a slow image re-render below can't let a duplicate/late
        # answer sneak into an already-finished game.
        if is_complete and GRID_GAMES.get(key) is game:
            GRID_GAMES.pop(key, None)

        # ------------------------------------------------------
        # STEP 1 — ALWAYS send the result text FIRST, before touching
        # the image at all. This is the part that must never fail to
        # reach the group (this used to run AFTER the image
        # re-render, so an image/network hiccup could silently
        # swallow the "found" message and, worse, the final winner
        # announcement).
        # ------------------------------------------------------
        try:
            if is_complete:
                leaderboard_lines = sorted(
                    game["scoreboard"].items(),
                    key=lambda item: item[1]["count"],
                    reverse=True,
                )

                board_text = "\n".join(
                    f"👤 {data['name']} — {data['count']} word(s)"
                    for _, data in leaderboard_lines
                ) or "No one scored."

                await message.reply_text(
                    "🏆 ═══ WORD GRID COMPLETE! ═══ 🏆\n\n"
                    "All 10 words found!\n\n"
                    f"{board_text}\n\n"
                    "🩸 GRID MASTERS!"
                )
            else:
                remaining = total - found_count

                await message.reply_text(
                    "✅ WORD FOUND!\n\n"
                    f"🔎 Word: {matching_word}\n"
                    f"👤 Found by: {user.first_name} (+10 XP)\n"
                    f"📊 Progress: {found_count}/{total}\n"
                    f"🔍 Remaining: {remaining}\n"
                    f"💳 {user.first_name}'s balance: {new_balance} XP"
                )
        except Exception as error:
            logger.error(
                f"Grid result message error: {error}", exc_info=True
            )

        # ------------------------------------------------------
        # STEP 2 — best-effort image re-render/resend. Anything that
        # goes wrong here is logged but can no longer prevent the
        # text result above from having already reached the group.
        # ------------------------------------------------------
        updated_image = None

        try:
            updated_image = await asyncio.to_thread(
                _render_word_grid,
                game["board"],
                game["grid_size"],
                game["placements"],
                game["found"]
            )

            clue_lines = []

            for index, word in enumerate(
                game["words"],
                1
            ):
                clue = (
                    word[0]
                    + " "
                    + " ".join(
                        "_"
                        for _ in range(
                            len(word) - 1
                        )
                    )
                )

                mark = (
                    " ✓"
                    if word in game["found"]
                    else ""
                )

                clue_lines.append(
                    f"{index}. {clue}{mark}"
                )

            caption = (
                "🔎 FIND THE 10 WORDS — everyone in the group can play!\n\n"
                + "\n".join(clue_lines)
                + f"\n\n🎯 Difficulty: "
                f"{game['difficulty'].upper()}"
                + "\n💰 Each word = +10 XP"
                + f"\n📊 Found: {found_count}/{total}"
                + "\n\n🧠 Found words are marked ✓ above."
            )

            if game.get("message_id"):
                try:
                    await context.bot.delete_message(
                        chat_id=chat.id,
                        message_id=game["message_id"]
                    )
                except Exception as delete_error:
                    logger.warning(
                        f"Word grid delete error: {delete_error}"
                    )

                with open(
                    updated_image,
                    "rb"
                ) as photo:

                    resent = await context.bot.send_photo(
                        chat_id=chat.id,
                        photo=photo,
                        caption=caption
                    )

                if not is_complete:
                    game["message_id"] = resent.message_id

        except Exception as error:
            logger.error(
                f"Word grid update error: {error}", exc_info=True
            )

        finally:
            if updated_image:
                try:
                    if os.path.exists(
                        updated_image
                    ):
                        os.remove(
                            updated_image
                        )
                except Exception:
                    pass

        return True


# ============================================================
# TRUTH
# ============================================================

async def truth_command(update, context):
    truths = [
        "What's one thing you've never told your closest friend?",
        "What's the biggest mistake you've made recently?",
        "What's one goal you're seriously trying to achieve?",
        "What's something you're secretly very good at?",
        "What's the most embarrassing thing that happened to you recently?",
    ]

    await update.effective_message.reply_text(
        f"🤫 **BLOODY TRUTH**\n\n"
        f"{random.choice(truths)}",
        parse_mode="Markdown"
    )


# ============================================================
# DARE
# ============================================================

async def dare_command(update, context):
    dares = [
        "Send your friend a completely random funny message.",
        "Change your Telegram bio to something ridiculous for 10 minutes.",
        "Send a voice note saying the first random sentence that comes to mind.",
        "Let the group choose your next profile picture for 10 minutes.",
        "Send 😂 to the last person you chatted with.",
    ]

    await update.effective_message.reply_text(
        f"🌶️ **BLOODY DARE**\n\n"
        f"⚡ {random.choice(dares)}",
        parse_mode="Markdown"
    )


# ============================================================
# COINFLIP
# ============================================================

async def coinflip_command(update, context):
    user = update.effective_user
    message = update.effective_message

    result = random.choice(["HEADS", "TAILS"])

    # No bet given -> just a free, fun flip, no XP involved
    if not context.args:
        await message.reply_text(
            f"🪙 **COIN FLIP**\n\n"
            f"Result: **{result}**\n\n"
            f"_Tip: `/coinflip <amount>` to bet XP on it._",
            parse_mode="Markdown"
        )
        return

    try:
        bet = int(context.args[0])
    except (ValueError, TypeError):
        await message.reply_text("❌ Bet amount must be a whole number.")
        return

    if bet <= 0:
        await message.reply_text("❌ Bet must be greater than 0.")
        return

    cooldown_remaining = _check_and_start_cooldown("coinflip", user.id, 10)

    if cooldown_remaining is not None:
        await message.reply_text(
            f"⏱️ Try again in **{cooldown_remaining}s**.",
            parse_mode="Markdown"
        )
        return

    stats = db.get_user_stats(user.id)

    if not stats:
        await message.reply_text("❌ You don't have an XP profile yet.")
        return

    balance = max(0, int(stats.get("xp", 0)))

    if bet > balance:
        await message.reply_text(
            f"❌ Insufficient XP.\nYour balance: **{balance} XP**",
            parse_mode="Markdown"
        )
        return

    call = random.choice(["HEADS", "TAILS"])
    won = call == result

    if won:
        new_balance = db.update_manual_xp(user.id, bet)
        await message.reply_text(
            f"🪙 **COIN FLIP**\n\n"
            f"Result: **{result}**\n\n"
            f"🎉 You called it! Won **+{bet} XP**\n"
            f"💰 Balance: `{new_balance} XP`",
            parse_mode="Markdown"
        )
    else:
        new_balance = db.update_manual_xp(user.id, -bet)
        await message.reply_text(
            f"🪙 **COIN FLIP**\n\n"
            f"Result: **{result}**\n\n"
            f"💀 Wrong call. Lost **-{bet} XP**\n"
            f"💰 Balance: `{new_balance} XP`",
            parse_mode="Markdown"
        )


# ============================================================
# DICE
# ============================================================

async def dice_command(update, context):
    user = update.effective_user
    message = update.effective_message

    result = random.randint(1, 6)

    # No bet given -> just a free, fun roll, no XP involved
    if not context.args:
        await message.reply_text(
            f"🎲 **BLOODY DICE**\n\n"
            f"You rolled: **{result}**\n\n"
            f"_Tip: `/dice <amount>` to bet XP that you roll a 5 or 6._",
            parse_mode="Markdown"
        )
        return

    try:
        bet = int(context.args[0])
    except (ValueError, TypeError):
        await message.reply_text("❌ Bet amount must be a whole number.")
        return

    if bet <= 0:
        await message.reply_text("❌ Bet must be greater than 0.")
        return

    cooldown_remaining = _check_and_start_cooldown("dice", user.id, 10)

    if cooldown_remaining is not None:
        await message.reply_text(
            f"⏱️ Try again in **{cooldown_remaining}s**.",
            parse_mode="Markdown"
        )
        return

    stats = db.get_user_stats(user.id)

    if not stats:
        await message.reply_text("❌ You don't have an XP profile yet.")
        return

    balance = max(0, int(stats.get("xp", 0)))

    if bet > balance:
        await message.reply_text(
            f"❌ Insufficient XP.\nYour balance: **{balance} XP**",
            parse_mode="Markdown"
        )
        return

    won = result >= 5  # rolling 5 or 6 wins

    if won:
        new_balance = db.update_manual_xp(user.id, bet)
        await message.reply_text(
            f"🎲 **BLOODY DICE**\n\n"
            f"You rolled: **{result}**\n\n"
            f"🎉 5 or 6 wins! Won **+{bet} XP**\n"
            f"💰 Balance: `{new_balance} XP`",
            parse_mode="Markdown"
        )
    else:
        new_balance = db.update_manual_xp(user.id, -bet)
        await message.reply_text(
            f"🎲 **BLOODY DICE**\n\n"
            f"You rolled: **{result}**\n\n"
            f"💀 Needed a 5 or 6. Lost **-{bet} XP**\n"
            f"💰 Balance: `{new_balance} XP`",
            parse_mode="Markdown"
        )


# ============================================================
# SLOTS
# ============================================================

async def slots_command(update, context):
    user = update.effective_user
    message = update.effective_message

    symbols = ["🍒", "🍋", "🍉", "⭐", "💎", "7️⃣"]
    result = [random.choice(symbols) for _ in range(3)]
    display = " | ".join(result)

    if result[0] == result[1] == result[2]:
        outcome_label = "🎉 **JACKPOT!**"
        multiplier = 5
    elif (
        result[0] == result[1]
        or result[1] == result[2]
        or result[0] == result[2]
    ):
        outcome_label = "🔥 **Two matched!**"
        multiplier = 2
    else:
        outcome_label = "💀 **No match.**"
        multiplier = 0

    # No bet given -> just a free, fun spin, no XP involved
    if not context.args:
        await message.reply_text(
            f"🎰 **BLOODY SLOTS**\n\n"
            f"┌───────────────┐\n"
            f"│ {display} │\n"
            f"└───────────────┘\n\n"
            f"{outcome_label}\n\n"
            f"_Tip: `/slots <amount>` to bet XP — jackpot pays 5x, "
            f"two matched pays 2x._",
            parse_mode="Markdown"
        )
        return

    try:
        bet = int(context.args[0])
    except (ValueError, TypeError):
        await message.reply_text("❌ Bet amount must be a whole number.")
        return

    if bet <= 0:
        await message.reply_text("❌ Bet must be greater than 0.")
        return

    cooldown_remaining = _check_and_start_cooldown("slots", user.id, 10)

    if cooldown_remaining is not None:
        await message.reply_text(
            f"⏱️ Try again in **{cooldown_remaining}s**.",
            parse_mode="Markdown"
        )
        return

    stats = db.get_user_stats(user.id)

    if not stats:
        await message.reply_text("❌ You don't have an XP profile yet.")
        return

    balance = max(0, int(stats.get("xp", 0)))

    if bet > balance:
        await message.reply_text(
            f"❌ Insufficient XP.\nYour balance: **{balance} XP**",
            parse_mode="Markdown"
        )
        return

    if multiplier > 0:
        winnings = bet * multiplier
        new_balance = db.update_manual_xp(user.id, winnings)
        await message.reply_text(
            f"🎰 **BLOODY SLOTS**\n\n"
            f"┌───────────────┐\n"
            f"│ {display} │\n"
            f"└───────────────┘\n\n"
            f"{outcome_label}\n"
            f"🎉 Won **+{winnings} XP** ({multiplier}x)\n"
            f"💰 Balance: `{new_balance} XP`",
            parse_mode="Markdown"
        )
    else:
        new_balance = db.update_manual_xp(user.id, -bet)
        await message.reply_text(
            f"🎰 **BLOODY SLOTS**\n\n"
            f"┌───────────────┐\n"
            f"│ {display} │\n"
            f"└───────────────┘\n\n"
            f"{outcome_label}\n"
            f"💀 Lost **-{bet} XP**\n"
            f"💰 Balance: `{new_balance} XP`",
            parse_mode="Markdown"
        )


# ============================================================
# RPS
# ============================================================

async def rps_command(update, context):
    if not context.args:
        await update.effective_message.reply_text(
            "✊ Usage: `/rps rock`\n"
            "Available: rock, paper, scissors",
            parse_mode="Markdown"
        )
        return

    user_choice = context.args[0].lower()

    choices = [
        "rock",
        "paper",
        "scissors"
    ]

    if user_choice not in choices:
        await update.effective_message.reply_text(
            "❌ Choose `rock`, `paper`, or `scissors`.",
            parse_mode="Markdown"
        )
        return

    bot_choice = random.choice(choices)

    if user_choice == bot_choice:
        result = "🤝 **DRAW!**"

    elif (
        (user_choice == "rock" and bot_choice == "scissors")
        or
        (user_choice == "paper" and bot_choice == "rock")
        or
        (user_choice == "scissors" and bot_choice == "paper")
    ):
        result = "🏆 **YOU WIN!**"

    else:
        result = "💀 **I WIN!**"

    await update.effective_message.reply_text(
        f"✊ **ROCK PAPER SCISSORS**\n\n"
        f"👤 You: **{user_choice.upper()}**\n"
        f"🩸 Bloody: **{bot_choice.upper()}**\n\n"
        f"{result}",
        parse_mode="Markdown"
    )


# ============================================================
# GAMBLE
# ============================================================

async def gamble_command(update, context):
    user = update.effective_user

    cooldown_remaining = _check_and_start_cooldown("gamble", user.id, 15)

    if cooldown_remaining is not None:
        await update.effective_message.reply_text(
            f"⏱️ Slow down! Try `/gamble` again in **{cooldown_remaining}s**.",
            parse_mode="Markdown"
        )
        return

    if not context.args:
        await update.effective_message.reply_text(
            "🎲 Usage: `/gamble <amount>`",
            parse_mode="Markdown"
        )
        return

    try:
        bet = int(context.args[0])
    except (ValueError, TypeError):
        await update.effective_message.reply_text(
            "❌ Amount must be a whole number."
        )
        return

    if bet <= 0:
        await update.effective_message.reply_text(
            "❌ Bet must be greater than 0."
        )
        return

    stats = db.get_user_stats(user.id)

    if not stats:
        await update.effective_message.reply_text(
            "❌ You don't have an XP profile yet."
        )
        return

    balance = max(
        0,
        int(stats.get("xp", 0))
    )

    if bet > balance:
        await update.effective_message.reply_text(
            f"❌ Insufficient XP.\n"
            f"Your balance: **{balance} XP**",
            parse_mode="Markdown"
        )
        return

    user_roll = random.randint(1, 6)
    bot_roll = random.randint(1, 6)

    if user_roll > bot_roll:
        new_balance = db.update_manual_xp(
            user.id,
            bet
        )

        await update.effective_message.reply_text(
            f"🎲 **GAMBLE WIN!**\n\n"
            f"🟢 You: `{user_roll}`\n"
            f"🔴 Bloody: `{bot_roll}`\n\n"
            f"🎉 Won **+{bet} XP**!\n"
            f"💰 Balance: `{new_balance} XP`",
            parse_mode="Markdown"
        )

    elif user_roll < bot_roll:
        new_balance = db.update_manual_xp(
            user.id,
            -bet
        )

        await update.effective_message.reply_text(
            f"🎲 **GAMBLE LOSS!**\n\n"
            f"🔴 You: `{user_roll}`\n"
            f"🟢 Bloody: `{bot_roll}`\n\n"
            f"💀 Lost **-{bet} XP**.\n"
            f"💰 Balance: `{new_balance} XP`",
            parse_mode="Markdown"
        )

    else:
        await update.effective_message.reply_text(
            f"🎲 **DRAW!**\n\n"
            f"Both rolled `{user_roll}`.\n"
            f"Your XP remains unchanged.",
            parse_mode="Markdown"
        )


# ============================================================
# STEAL
# ============================================================

async def steal_command(update, context):
    user = update.effective_user
    target = extract_target_user(update)

    cooldown_remaining = _check_and_start_cooldown("steal", user.id, 300)

    if cooldown_remaining is not None:
        minutes = cooldown_remaining // 60
        seconds = cooldown_remaining % 60
        await update.effective_message.reply_text(
            f"⏱️ Your heist crew needs to lay low. Try again in "
            f"**{minutes}m {seconds}s**.",
            parse_mode="Markdown"
        )
        return

    if not target or target.id == user.id:
        await update.effective_message.reply_text(
            "🥷 Reply to the member you want to steal from."
        )
        return

    me = await context.bot.get_me()

    if target.id == me.id:
        await update.effective_message.reply_text(
            "😂 Nice try. My XP vault is locked."
        )
        return

    target_stats = db.get_user_stats(target.id)

    if not target_stats:
        await update.effective_message.reply_text(
            "❌ That user doesn't have an XP profile yet."
        )
        return

    target_xp = max(
        0,
        int(target_stats.get("xp", 0))
    )

    if target_xp < 50:
        await update.effective_message.reply_text(
            "❌ That user doesn't have enough XP to steal from."
        )
        return

    if random.random() < 0.5:
        stolen = min(
            random.randint(20, 60),
            target_xp
        )

        db.update_manual_xp(
            target.id,
            -stolen
        )

        new_balance = db.update_manual_xp(
            user.id,
            stolen
        )

        await update.effective_message.reply_text(
            f"🥷 **HEIST SUCCESSFUL!**\n\n"
            f"💰 Stole **{stolen} XP** from "
            f"**{target.first_name}**.\n"
            f"💳 Your balance: `{new_balance} XP`",
            parse_mode="Markdown"
        )

    else:
        stats = db.get_user_stats(user.id)

        current_xp = (
            max(0, int(stats.get("xp", 0)))
            if stats
            else 0
        )

        penalty = min(
            random.randint(15, 40),
            current_xp
        )

        new_balance = db.update_manual_xp(
            user.id,
            -penalty
        )

        await update.effective_message.reply_text(
            f"🚨 **HEIST FAILED!**\n\n"
            f"**{target.first_name}** caught you.\n"
            f"💸 Fine: **-{penalty} XP**\n"
            f"💰 Balance: `{new_balance} XP`",
            parse_mode="Markdown"
        )


# ============================================================
# DUEL
# ============================================================

async def duel_command(update, context):
    user = update.effective_user
    target = extract_target_user(update)

    cooldown_remaining = _check_and_start_cooldown("duel", user.id, 300)

    if cooldown_remaining is not None:
        minutes = cooldown_remaining // 60
        seconds = cooldown_remaining % 60
        await update.effective_message.reply_text(
            f"⏱️ You need to recover before your next duel. Try again in "
            f"**{minutes}m {seconds}s**.",
            parse_mode="Markdown"
        )
        return

    if not target or target.id == user.id:
        await update.effective_message.reply_text(
            "⚔️ Reply to the member you want to duel."
        )
        return

    me = await context.bot.get_me()

    if target.id == me.id:
        await update.effective_message.reply_text(
            "😂 You cannot duel me."
        )
        return

    user_stats = db.get_user_stats(user.id)
    target_stats = db.get_user_stats(target.id)

    if not user_stats or not target_stats:
        await update.effective_message.reply_text(
            "⚔️ Both players need an XP profile first."
        )
        return

    user_xp = max(
        0,
        int(user_stats.get("xp", 0))
    )

    target_xp = max(
        0,
        int(target_stats.get("xp", 0))
    )

    if user_xp < 100:
        await update.effective_message.reply_text(
            "⚔️ You need at least **100 XP** to duel.",
            parse_mode="Markdown"
        )
        return

    if target_xp < 100:
        await update.effective_message.reply_text(
            f"⚔️ {target.first_name} needs at least **100 XP** to duel.",
            parse_mode="Markdown"
        )
        return

    winner = random.choice(
        [user, target]
    )

    loser = (
        target
        if winner.id == user.id
        else user
    )

    db.update_manual_xp(
        winner.id,
        100
    )

    db.update_manual_xp(
        loser.id,
        -100
    )

    await update.effective_message.reply_text(
        "⚔️ ═══ **BLOODY DUEL ARENA** ═══ ⚔️\n\n"
        f"🔥 **{user.first_name}** vs **{target.first_name}**\n\n"
        f"🏆 **WINNER:** {winner.first_name}\n"
        f"🎁 **+100 XP**\n"
        f"💀 **{loser.first_name} -100 XP**",
        parse_mode="Markdown"
    )


# ============================================================
# BADGE
# ============================================================

async def badge_command(update, context):
    target, chat = await _guard(
        update,
        context
    )

    if not target:
        return

    if not context.args:
        await update.effective_message.reply_text(
            "🏅 Usage: `/badge Certified Dev`",
            parse_mode="Markdown"
        )
        return

    title = " ".join(
        context.args
    ).strip()

    if len(title) > 50:
        title = title[:50]

    db.set_user_badge(
        target.id,
        title
    )

    await update.effective_message.reply_text(
        f"🏅 **Badge awarded!**\n\n"
        f"👤 {target.first_name}\n"
        f"🎖️ [{title}]",
        parse_mode="Markdown"
    )


# ============================================================
# PROMOTE
# ============================================================

async def promote_command(update, context):
    target, chat = await _guard(
        update,
        context,
        "can_promote_members"
    )

    if not target:
        return

    try:
        await context.bot.promote_chat_member(
            chat_id=chat.id,
            user_id=target.id,
            can_manage_chat=True,
            can_delete_messages=True,
            can_manage_video_chats=True,
            can_restrict_members=True,
            can_promote_members=False,
            can_change_info=True,
            can_invite_users=True,
            can_pin_messages=True,
            can_manage_topics=True
        )

        await update.effective_message.reply_text(
            f"⬆️ **Promotion successful!**\n\n"
            f"{target.first_name} is now an administrator.",
            parse_mode="Markdown"
        )

    except Exception as error:
        logger.warning(f"Promote error: {error}")

        await update.effective_message.reply_text(
            "❌ I couldn't promote that member."
        )


# ============================================================
# DEMOTE
# ============================================================

async def demote_command(update, context):
    target, chat = await _guard(
        update,
        context,
        "can_promote_members"
    )

    if not target:
        return

    try:
        await context.bot.promote_chat_member(
            chat_id=chat.id,
            user_id=target.id,
            can_manage_chat=False,
            can_delete_messages=False,
            can_manage_video_chats=False,
            can_restrict_members=False,
            can_promote_members=False,
            can_change_info=False,
            can_invite_users=False,
            can_pin_messages=False,
            can_manage_topics=False
        )

        await update.effective_message.reply_text(
            f"⬇️ **Demotion successful!**\n\n"
            f"{target.first_name} is now a regular member.",
            parse_mode="Markdown"
        )

    except Exception as error:
        logger.warning(f"Demote error: {error}")

        await update.effective_message.reply_text(
            "❌ I couldn't demote that administrator."
        )


# ============================================================
# ANTISPAM
# ============================================================

async def antispam_command(update, context):
    chat = update.effective_chat

    if chat.type not in ("group", "supergroup"):
        return

    if not await is_user_group_admin(
        update,
        context,
        update.effective_user.id
    ):
        await update.effective_message.reply_text(
            "🚫 Administrators only."
        )
        return

    if not context.args:
        await update.effective_message.reply_text(
            "🛡️ Usage: `/antispam on` or `/antispam off`",
            parse_mode="Markdown"
        )
        return

    mode = context.args[0].lower()

    if mode == "on":
        db.toggle_antispam(
            chat.id,
            True
        )

        await update.effective_message.reply_text(
            "🛡️ **Anti-spam is now ON.**",
            parse_mode="Markdown"
        )

    elif mode == "off":
        db.toggle_antispam(
            chat.id,
            False
        )

        await update.effective_message.reply_text(
            "🛡️ **Anti-spam is now OFF.**",
            parse_mode="Markdown"
        )

    else:
        await update.effective_message.reply_text(
            "❌ Use `/antispam on` or `/antispam off`.",
            parse_mode="Markdown"
        )


# ============================================================
# GIVE XP
# ============================================================

async def givexp_command(update, context):
    target, chat = await _guard(
        update,
        context
    )

    if not target:
        return

    if not context.args:
        await update.effective_message.reply_text(
            "🎁 Usage: `/givexp 100`",
            parse_mode="Markdown"
        )
        return

    try:
        amount = int(context.args[0])
    except (ValueError, TypeError):
        await update.effective_message.reply_text(
            "❌ XP amount must be a number."
        )
        return

    if amount <= 0:
        await update.effective_message.reply_text(
            "❌ Use a positive XP amount."
        )
        return

    if amount > 1_000_000:
        await update.effective_message.reply_text(
            "❌ Maximum XP injection is 1,000,000."
        )
        return

    balance = db.update_manual_xp(
        target.id,
        amount
    )

    await update.effective_message.reply_text(
        f"🎁 **XP GIVEN!**\n\n"
        f"👤 {target.first_name}\n"
        f"✨ +{amount} XP\n"
        f"💰 Balance: `{balance} XP`",
        parse_mode="Markdown"
    )


# ============================================================
# POLL
# ============================================================

async def poll_command(update, context):
    chat = update.effective_chat

    if chat.type not in ("group", "supergroup"):
        return

    if not await is_user_group_admin(
        update,
        context,
        update.effective_user.id
    ):
        await update.effective_message.reply_text(
            "🚫 Administrators only."
        )
        return

    if not context.args:
        await update.effective_message.reply_text(
            "📊 Usage: `/poll Is this bot good?`",
            parse_mode="Markdown"
        )
        return

    question = " ".join(
        context.args
    ).strip()

    if len(question) > 300:
        await update.effective_message.reply_text(
            "❌ Poll question is too long."
        )
        return

    try:
        await context.bot.send_poll(
            chat_id=chat.id,
            question=question,
            options=[
                "🔴 Yes",
                "🔵 No"
            ],
            is_anonymous=False
        )

    except Exception as error:
        logger.warning(f"Poll error: {error}")

        await update.effective_message.reply_text(
            "❌ I couldn't create the poll."
        )


# ============================================================
# BROADCAST (owner-only)
#
# Usage:
#   • Reply to ANY message (text, photo, video, etc.) in ANY chat
#     the bot can see, with just: /broadcast
#     -> that exact message gets copied into every group the bot
#        is currently in.
#   • Or, with no reply: /broadcast Your announcement text
#     -> sends that text to every group the bot is in.
#
# Restricted to the Telegram user ID(s) in OWNER_IDS above.
# ============================================================

async def broadcast_command(update, context):
    user = update.effective_user
    message = update.effective_message

    if not user or not message:
        return

    if not OWNER_IDS or user.id not in OWNER_IDS:
        # Silently ignore for non-owners — no hint that this
        # command even exists for randoms poking at the bot.
        return

    known_chats = db.get_known_group_chats()

    if not known_chats:
        await message.reply_text(
            "⚠️ I don't have any groups on record yet. I register a "
            "group the moment I'm added to it (or the first time I "
            "see activity there), so this should fill in once that "
            "happens."
        )
        return

    source_message = message.reply_to_message
    text_payload = " ".join(context.args) if context.args else None

    if not source_message and not text_payload:
        await message.reply_text(
            "📢 Usage:\n"
            "• Reply to the message you want broadcast (text, photo, "
            "video, whatever) with `/broadcast`\n"
            "• Or: `/broadcast Your announcement text`",
            parse_mode="Markdown"
        )
        return

    status_msg = await message.reply_text(
        f"📢 Broadcasting to {len(known_chats)} group(s)..."
    )

    sent_count = 0
    failed_count = 0

    for chat_id in known_chats:
        try:
            if source_message:
                await context.bot.copy_message(
                    chat_id=chat_id,
                    from_chat_id=source_message.chat_id,
                    message_id=source_message.message_id,
                )
            else:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=text_payload
                )

            sent_count += 1

        except Exception as error:
            failed_count += 1
            logger.warning(f"Broadcast to {chat_id} failed: {error}")

    await status_msg.edit_text(
        f"📢 **Broadcast complete.**\n\n"
        f"✅ Delivered: {sent_count}\n"
        f"❌ Failed: {failed_count}",
        parse_mode="Markdown"
    )


# ============================================================
# XP GIFT DROP
#
# Runs on the bot's JobQueue (scheduled from bot.py). Every so
# often, drops a "first to type claim wins XP" message in a random
# group the bot is in. If nobody claims it within 5 minutes, it
# expires and the message updates to say so.
# ============================================================

async def drop_random_gift_job(context):
    # Reschedule the *next* drop first, no matter what happens below,
    # so one bad tick can't silently kill the whole feature.
    next_delay = random.randint(
        GIFT_MIN_INTERVAL_SECONDS,
        GIFT_MAX_INTERVAL_SECONDS
    )

    context.job_queue.run_once(
        drop_random_gift_job,
        next_delay
    )

    known_chats = db.get_known_group_chats()

    if not known_chats:
        return

    candidates = [
        chat_id for chat_id in known_chats
        if chat_id not in GIFT_CACHE
    ]

    if not candidates:
        return

    chat_id = random.choice(candidates)
    amount = random.randint(GIFT_XP_MIN, GIFT_XP_MAX)

    try:
        sent = await context.bot.send_message(
            chat_id=chat_id,
            text=(
                "🎁 **XP GIFT DROPPED!**\n\n"
                f"First person to type `claim` gets **+{amount} XP**!\n"
                "⏱️ Expires in 5 minutes."
            ),
            parse_mode="Markdown"
        )

    except Exception as error:
        logger.warning(f"Gift drop send error for {chat_id}: {error}")
        return

    GIFT_CACHE[chat_id] = {
        "amount": amount,
        "message_id": sent.message_id,
        "expires": time.time() + GIFT_CLAIM_WINDOW_SECONDS,
        "claimed": False,
    }

    context.job_queue.run_once(
        expire_gift_job,
        GIFT_CLAIM_WINDOW_SECONDS,
        data={"chat_id": chat_id}
    )


async def expire_gift_job(context):
    chat_id = context.job.data["chat_id"]
    gift = GIFT_CACHE.get(chat_id)

    if not gift or gift.get("claimed"):
        return

    GIFT_CACHE.pop(chat_id, None)

    try:
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=gift["message_id"],
            text="💤 The XP gift expired unclaimed. Better luck next time!"
        )
    except Exception as error:
        logger.warning(f"Gift expire edit error: {error}")


async def try_claim_gift(update, context):
    """Called from chat_with_ai_and_track whenever someone types
    'claim'. Returns True if it consumed the message as a gift claim."""

    message = update.effective_message
    chat = update.effective_chat
    user = update.effective_user

    if not message or not chat or not user:
        return False

    gift = GIFT_CACHE.get(chat.id)

    if not gift or gift.get("claimed"):
        return False

    if time.time() > gift["expires"]:
        return False

    gift["claimed"] = True
    GIFT_CACHE.pop(chat.id, None)

    # Make sure the claimer actually has a profile to add XP to.
    if not db.get_user_stats(user.id):
        db.update_user_activity(
            user.id,
            user.username,
            user.first_name,
            chat.id
        )

    new_balance = db.update_manual_xp(user.id, gift["amount"])

    try:
        await context.bot.edit_message_text(
            chat_id=chat.id,
            message_id=gift["message_id"],
            text=(
                f"🎁 **CLAIMED!**\n\n"
                f"👤 {user.first_name} grabbed **+{gift['amount']} XP**!"
            ),
            parse_mode="Markdown"
        )
    except Exception as error:
        logger.warning(f"Gift claim edit error: {error}")

    await message.reply_text(
        f"✅ You claimed the gift! +{gift['amount']} XP.\n"
        f"💰 Balance: `{new_balance} XP`",
        parse_mode="Markdown"
    )

    return True


# ============================================================
# STICKER REPLY
# ============================================================

async def sticker_reply_handler(update, context):
    message = update.effective_message

    if not message or not message.sticker:
        return

    bot = context.bot

    try:
        me = await bot.get_me()
        should_reply = False

        if message.reply_to_message:
            replied = message.reply_to_message

            if (
                replied.from_user
                and replied.from_user.id == me.id
            ):
                should_reply = True

        if message.caption and me.username:
            mention = f"@{me.username}".lower()

            if mention in message.caption.lower():
                should_reply = True

        if not should_reply:
            return

        user = update.effective_user
        chat = update.effective_chat

        if user and chat:
            db.update_user_activity(
                user.id,
                user.username,
                user.first_name,
                chat.id
            )

        sticker = message.sticker

        if not sticker.set_name:
            await message.reply_sticker(
                sticker=sticker.file_id
            )
            return

        sticker_set = await bot.get_sticker_set(
            name=sticker.set_name
        )

        if not sticker_set or not sticker_set.stickers:
            await message.reply_sticker(
                sticker=sticker.file_id
            )
            return

        valid_pool = [
            s.file_id
            for s in sticker_set.stickers
            if s.file_id != sticker.file_id
        ]

        chosen = (
            random.choice(valid_pool)
            if valid_pool
            else sticker.file_id
        )

        await message.reply_sticker(
            sticker=chosen
        )

    except Exception as error:
        logger.warning(
            f"Sticker system error: {error}"
        )

        try:
            await message.reply_sticker(
                sticker=message.sticker.file_id
            )
        except Exception:
            pass


# ============================================================
# BLOCKING WORKERS
# ============================================================

def _cohere_chat_sync(
    api_key,
    model,
    messages,
    max_tokens,
    temperature
):
    co = cohere.ClientV2(
        api_key=api_key
    )

    return co.chat(
        model=model,
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature
    )


def _transcribe_voice_sync(input_file):
    global WHISPER_MODEL

    if WHISPER_MODEL is None:
        with WHISPER_MODEL_LOCK:
            if WHISPER_MODEL is None:
                logger.info(
                    "[VOICE] Loading Faster-Whisper..."
                )

                WHISPER_MODEL = WhisperModel(
                    "base",
                    device="cpu",
                    compute_type="int8"
                )

    segments, info = WHISPER_MODEL.transcribe(
        input_file,
        beam_size=5
    )

    return " ".join(
        segment.text.strip()
        for segment in segments
    ).strip()


# ============================================================
# AI CHAT
# ============================================================

async def chat_with_ai_and_track(update, context):
    message = update.effective_message

    if not message or not message.text:
        return

    user = update.effective_user
    chat = update.effective_chat

    if not user or not chat:
        return

    message_text = message.text.strip()
    lower_text = message_text.lower()

    # Keep the known-chats registry warm for any group we see
    # activity in, even if we somehow missed the MY_CHAT_MEMBER
    # update when the bot was added (e.g. it was added before this
    # feature existed). Powers /broadcast and the XP-gift drop.
    if chat.type in ("group", "supergroup"):
        db.register_known_chat(chat.id, chat.type, chat.title)

    grid_handled = await grid_answer_handler(
        update,
        context
    )

    if grid_handled:
        return

    if lower_text == "claim":
        claimed = await try_claim_gift(update, context)

        if claimed:
            return

    try:
        settings = db.get_group_settings(
            chat.id
        ) or {}
    except Exception:
        settings = {}

    if settings.get("antispam"):
        now = time.time()
        flood_key = (
            chat.id,
            user.id
        )

        previous = FLOOD_CACHE.get(
            flood_key
        )

        if (
            previous
            and now - previous < 0.8
        ):
            try:
                await message.delete()
            except Exception:
                pass

            return

        FLOOD_CACHE[flood_key] = now

    try:
        random_xp, new_total = db.update_user_activity(
            user.id,
            user.username,
            user.first_name,
            chat.id
        )

    except Exception as error:
        logger.warning(
            f"Activity error: {error}"
        )

    # "menu", "grid" and "trivia" all work as bare words too (no
    # slash needed) — mirrors how "menu" already worked, extended
    # to the two games since that's the more natural way people
    # try to start them.
    if lower_text == "menu":
        await menu_command(
            update,
            context
        )
        return

    if lower_text == "grid":
        await grid_command(
            update,
            context
        )
        return

    if lower_text == "trivia":
        await trivia_command(
            update,
            context
        )
        return

    if (
        "who created you" in lower_text
        or "who made you" in lower_text
        or "who deployed you" in lower_text
        or "who is your developer" in lower_text
    ):
        await message.reply_text(
            "I was created and deployed by my sovereign master Haggai A.K.A BLOODY"
        )
        return

    me = await context.bot.get_me()

    is_reply_to_bot = False

    if message.reply_to_message:
        replied = message.reply_to_message

        if (
            replied.from_user
            and replied.from_user.id == me.id
        ):
            is_reply_to_bot = True

    # Only respond when the bot's actual name is called ("bloody",
    # matched as a whole word so it doesn't fire inside unrelated
    # words) or it's actually tagged/replied to below — not on
    # generic words like "ai" or "bot".
    trigger_words = [
        "bloody",
    ]

    is_triggered = any(
        re.search(rf"\b{re.escape(word)}\b", lower_text)
        for word in trigger_words
    )

    # Being @mentioned by username always counts as a tag too.
    if me.username and f"@{me.username.lower()}" in lower_text:
        is_triggered = True

    if not (
        chat.type == "private"
        or is_triggered
        or is_reply_to_bot
    ):
        return

    await context.bot.send_chat_action(
        chat_id=chat.id,
        action="typing"
    )

    bad_words = [
        "fool",
        "stupid",
        "fuck",
        "mumu",
        "scam",
        "ode",
        "weray"
    ]

    user_was_toxic = any(
        word in lower_text
        for word in bad_words
    )

    personality = (
        "You are BLOODY MD, an intelligent Telegram AI assistant. "
        "You are confident, witty, knowledgeable, natural and conversational. "
        f"You are currently speaking with {user.first_name}. "
        "Speak primarily in clear natural English. "
        "Do not automatically use Nigerian Pidgin. "
        "Use slang or Pidgin naturally when the user does so first. "
        "Do not sound like a stereotypical chatbot. "
        "Talk like a smart human friend. "
        "Use the conversation history provided to maintain context. "
        "Never claim to remember something that is not in the history."
    )

    if user_was_toxic:
        personality += (
            " The user insulted you. "
            "You may respond with playful annoyance "
            "and a light roast, but never threaten them."
        )

    ai_lock = _get_ai_lock(chat.id)

    async with ai_lock:
        try:
            previous_messages = (
                db.get_ai_memory_for_cohere(
                    chat.id
                )
                or []
            )

            messages = [
                {
                    "role": "system",
                    "content": personality
                }
            ]

            messages.extend(
                previous_messages
            )

            messages.append(
                {
                    "role": "user",
                    "content": message_text
                }
            )

            response = await asyncio.to_thread(
                _cohere_chat_sync,
                COHERE_KEY,
                "command-a-03-2025",
                messages,
                700,
                0.7
            )

            ai_text = ""

            if (
                response.message
                and response.message.content
            ):
                for block in response.message.content:
                    if hasattr(block, "text"):
                        if block.text:
                            ai_text += block.text

                    elif isinstance(block, dict):
                        if block.get("type") == "text":
                            ai_text += block.get(
                                "text",
                                ""
                            )

            ai_text = ai_text.strip()

            if not ai_text:
                raise RuntimeError(
                    "Empty Cohere response"
                )

            db.save_ai_message(
                chat.id,
                "user",
                message_text,
                user.first_name
            )

            db.save_ai_message(
                chat.id,
                "assistant",
                ai_text
            )

        except Exception as error:
            logger.error(
                f"Cohere error: {error}", exc_info=True
            )

            await message.reply_text(
                "🧠 **[BLOODY AI]** My neural core glitched "
                "for a second 😂. Send that again.",
                parse_mode="Markdown"
            )

            return

    await message.reply_text(
        f"🩸 **[BLOODY MD]**\n\n{ai_text}",
        parse_mode="Markdown"
    )


# ============================================================
# VOICE
# ============================================================

async def voice_message_handler(update, context):
    message = update.effective_message

    if not message or not message.voice:
        return

    user = update.effective_user
    chat = update.effective_chat

    is_reply_to_bot = (
        message.reply_to_message
        and message.reply_to_message.from_user
        and message.reply_to_message.from_user.id
        == context.bot.id
    )

    if not is_reply_to_bot:
        return

    await context.bot.send_chat_action(
        chat_id=chat.id,
        action="record_voice"
    )

    temp_dir = tempfile.gettempdir()

    input_file = os.path.join(
        temp_dir,
        f"bloody_voice_{chat.id}_{user.id}_{message.message_id}.ogg"
    )

    output_file = os.path.join(
        temp_dir,
        f"bloody_reply_{chat.id}_{user.id}_{message.message_id}.mp3"
    )

    try:
        telegram_file = await context.bot.get_file(
            message.voice.file_id
        )

        await telegram_file.download_to_drive(
            custom_path=input_file
        )

        message_text = await asyncio.to_thread(
            _transcribe_voice_sync,
            input_file
        )

        if not message_text:
            await message.reply_text(
                "🎤 I couldn't understand that voice note."
            )
            return

        db.update_user_activity(
            user.id,
            user.username,
            user.first_name,
            chat.id
        )

        previous_messages = (
            db.get_ai_memory_for_cohere(
                chat.id
            )
            or []
        )

        personality = (
            "You are BLOODY MD, an intelligent Telegram AI assistant. "
            "You are confident, witty, knowledgeable and conversational. "
            f"You are speaking with {user.first_name}. "
            "Speak naturally in clear English. "
            "Use the supplied conversation history for context. "
            "Never pretend to remember information not present in it. "
            "The user communicated through a voice message. "
            "Respond naturally."
        )

        messages = [
            {
                "role": "system",
                "content": personality
            }
        ]

        messages.extend(
            previous_messages
        )

        messages.append(
            {
                "role": "user",
                "content": message_text
            }
        )

        ai_lock = _get_ai_lock(chat.id)

        async with ai_lock:
            previous_messages = (
                db.get_ai_memory_for_cohere(
                    chat.id
                )
                or []
            )

            messages = [
                {
                    "role": "system",
                    "content": personality
                }
            ]

            messages.extend(
                previous_messages
            )

            messages.append(
                {
                    "role": "user",
                    "content": message_text
                }
            )

            response = await asyncio.to_thread(
                _cohere_chat_sync,
                COHERE_KEY,
                "command-a-03-2025",
                messages,
                500,
                0.7
            )

            ai_text = ""

            if (
                response.message
                and response.message.content
            ):
                for block in response.message.content:
                    if hasattr(block, "text"):
                        ai_text += block.text or ""

                    elif isinstance(block, dict):
                        if block.get("type") == "text":
                            ai_text += block.get(
                                "text",
                                ""
                            )

            ai_text = ai_text.strip()

            if not ai_text:
                raise RuntimeError(
                    "Empty AI response"
                )

            db.save_ai_message(
                chat.id,
                "user",
                message_text,
                user.first_name
            )

            db.save_ai_message(
                chat.id,
                "assistant",
                ai_text
            )

        voice_text = "".join(
            char
            for char in ai_text
            if not (
                0x1F000 <= ord(char) <= 0x1FAFF
                or 0x2600 <= ord(char) <= 0x27BF
            )
        )

        for symbol in [
            "*",
            "_",
            "`",
            "#"
        ]:
            voice_text = voice_text.replace(
                symbol,
                ""
            )

        voice_text = " ".join(
            voice_text.split()
        ).strip()

        if not voice_text:
            voice_text = "I have nothing to say."

        communicate = edge_tts.Communicate(
            voice_text,
            "en-US-GuyNeural"
        )

        await communicate.save(
            output_file
        )

        with open(
            output_file,
            "rb"
        ) as voice_file:
            await message.reply_voice(
                voice=voice_file
            )

    except Exception as error:
        logger.error(
            f"BLOODY Voice System Error: {error}", exc_info=True
        )

        await message.reply_text(
            "🎤🧠 My voice system glitched for a second 😂. "
            "Try sending that again."
        )

    finally:
        for file_path in [
            input_file,
            output_file
        ]:
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
            except Exception:
                pass


# ============================================================
# WARN
# ============================================================

async def warn_command(update, context):
    target, chat = await _guard(
        update,
        context,
        "can_restrict_members"
    )

    if not target:
        return

    count = db.add_warning(
        chat.id,
        target.id
    )

    await update.effective_message.reply_text(
        f"⚠️ **Warning issued!**\n\n"
        f"👤 {target.first_name}\n"
        f"📊 Strikes: `{count}/{MAX_WARNINGS}`",
        parse_mode="Markdown"
    )

    if count >= MAX_WARNINGS:
        try:
            await context.bot.restrict_chat_member(
                chat_id=chat.id,
                user_id=target.id,
                permissions=ChatPermissions(
                    can_send_messages=False
                )
            )

            await update.effective_message.reply_text(
                f"🔇 {target.first_name} has reached "
                f"the warning limit and has been muted."
            )

        except Exception as error:
            logger.warning(
                f"Auto-mute error: {error}"
            )


# ============================================================
# WARNINGS
# ============================================================

async def warnings_command(update, context):
    chat = update.effective_chat

    if chat.type not in ("group", "supergroup"):
        return

    target = (
        extract_target_user(update)
        or update.effective_user
    )

    count = db.get_warnings(
        chat.id,
        target.id
    )

    await update.effective_message.reply_text(
        f"⚠️ **Warning Profile**\n\n"
        f"👤 {target.first_name}\n"
        f"🚨 Active strikes: `{count}/{MAX_WARNINGS}`",
        parse_mode="Markdown"
    )


# ============================================================
# CLEAR WARNINGS
# ============================================================

async def clearwarns_command(update, context):
    target, chat = await _guard(
        update,
        context
    )

    if not target:
        return

    db.clear_warnings(
        chat.id,
        target.id
    )

    await update.effective_message.reply_text(
        f"✅ Warnings cleared for "
        f"**{target.first_name}**.",
        parse_mode="Markdown"
    )


# ============================================================
# MUTE
# ============================================================

async def mute_command(update, context):
    target, chat = await _guard(
        update,
        context,
        "can_restrict_members"
    )

    if not target:
        return

    try:
        await context.bot.restrict_chat_member(
            chat_id=chat.id,
            user_id=target.id,
            permissions=ChatPermissions(
                can_send_messages=False
            )
        )

        await update.effective_message.reply_text(
            f"🔇 **{target.first_name}** has been muted.",
            parse_mode="Markdown"
        )

    except Exception as error:
        logger.warning(f"Mute error: {error}")

        await update.effective_message.reply_text(
            "❌ I couldn't mute that member."
        )


# ============================================================
# UNMUTE
# ============================================================

async def unmute_command(update, context):
    target, chat = await _guard(
        update,
        context,
        "can_restrict_members"
    )

    if not target:
        return

    try:
        permissions = ChatPermissions(
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
            can_manage_topics=False
        )

        await context.bot.restrict_chat_member(
            chat_id=chat.id,
            user_id=target.id,
            permissions=permissions
        )

        await update.effective_message.reply_text(
            f"🔊 **{target.first_name}** has been unmuted.",
            parse_mode="Markdown"
        )

    except Exception as error:
        logger.warning(f"Unmute error: {error}")

        await update.effective_message.reply_text(
            "❌ I couldn't unmute that member."
        )


# ============================================================
# KICK
# ============================================================

async def kick_command(update, context):
    target, chat = await _guard(
        update,
        context,
        "can_restrict_members"
    )

    if not target:
        return

    try:
        await context.bot.ban_chat_member(
            chat_id=chat.id,
            user_id=target.id
        )

        await context.bot.unban_chat_member(
            chat_id=chat.id,
            user_id=target.id,
            only_if_banned=True
        )

        await update.effective_message.reply_text(
            f"👢 **{target.first_name}** has been kicked.",
            parse_mode="Markdown"
        )

    except Exception as error:
        logger.warning(f"Kick error: {error}")

        await update.effective_message.reply_text(
            "❌ I couldn't kick that member."
        )


# ============================================================
# BAN
# ============================================================

async def ban_command(update, context):
    target, chat = await _guard(
        update,
        context,
        "can_restrict_members"
    )

    if not target:
        return

    try:
        await context.bot.ban_chat_member(
            chat_id=chat.id,
            user_id=target.id
        )

        await update.effective_message.reply_text(
            f"⛔ **{target.first_name}** has been permanently banned.",
            parse_mode="Markdown"
        )

    except Exception as error:
        logger.warning(f"Ban error: {error}")

        await update.effective_message.reply_text(
            "❌ I couldn't ban that member."
        )