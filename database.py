import json
import os
import random
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

DB_FILE = "bot_data.json"

# ============================================================
# 🩸 BLOODY MD — DATABASE / SYSTEM FOUNDATION
#
# PERFORMANCE NOTE:
# The database now lives in memory at all times. Every function
# below reads/writes the in-memory dict directly (this takes
# microseconds, not milliseconds), so calling these functions
# from inside your async handlers no longer blocks the bot for
# other users.
#
# Saving to disk still happens, but it happens on a single
# background writer thread, so the handler that triggered the
# save returns immediately without waiting for the disk write
# to finish. A threading.Lock protects the in-memory dict since
# the writer thread and the main thread can touch it at
# overlapping times.
# ============================================================

MAX_AI_MEMORY = 20

_LOCK = threading.RLock()
_WRITER = ThreadPoolExecutor(max_workers=1)
_DB = None  # loaded once, on first use


# ============================================================
# DEFAULT DATABASE
# ============================================================

def default_database():
    return {
        "warnings": {},
        "settings": {},
        "users": {},
        "active_recognition": {},
        "ai_memory": {},

        # NEW SYSTEMS
        "economy": {},
        "games": {},
        "puzzles": {},
        "achievements": {},
        "group_stats": {},
        "cooldowns": {},

        # Registry of every chat the bot is currently a member of.
        # Used by /broadcast so it knows where to send announcements
        # without you having to list your groups manually.
        "known_chats": {},
    }


# ============================================================
# LOAD / INIT (disk -> memory, only ever runs once)
# ============================================================

def _load_from_disk():
    if not os.path.exists(DB_FILE):
        db = default_database()
        _write_to_disk_sync(db)
        return db

    try:
        with open(DB_FILE, "r", encoding="utf-8") as f:
            db = json.load(f)

        defaults = default_database()

        for section, value in defaults.items():
            db.setdefault(section, value)

        return db

    except Exception:
        print("[DATABASE] Database was damaged. Creating fresh database.")
        db = default_database()
        _write_to_disk_sync(db)
        return db


def _ensure_loaded():
    global _DB

    if _DB is None:
        with _LOCK:
            if _DB is None:
                _DB = _load_from_disk()

    return _DB


# ============================================================
# SAVE (memory -> disk, runs on a background thread)
# ============================================================

def _write_to_disk_sync(data):
    """Runs on the background writer thread. Never call this
    directly from a handler — use _schedule_save() instead."""

    temp_file = DB_FILE + ".tmp"

    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

    os.replace(temp_file, DB_FILE)


def _schedule_save():
    """Takes a snapshot of the current in-memory DB and hands the
    disk write off to the background thread. Returns immediately
    — does NOT block the caller."""

    with _LOCK:
        # shallow copy of the top-level dict is enough here since
        # json.dump will serialize nested structures at write time,
        # and all mutation happens while holding _LOCK.
        snapshot = json.loads(json.dumps(_DB))

    _WRITER.submit(_write_to_disk_sync, snapshot)


# ============================================================
# PUBLIC-FACING HELPERS
#
# Kept for anything that used to call load_db()/save_db()
# directly. They now operate on the in-memory copy.
# ============================================================

def load_db():
    with _LOCK:
        return _ensure_loaded()


def save_db(data):
    global _DB

    with _LOCK:
        _DB = data

    _schedule_save()


# ============================================================
# GROUP SETTINGS
# ============================================================

def get_group_settings(chat_id):
    with _LOCK:
        db = _ensure_loaded()
        c_id = str(chat_id)

        if c_id not in db["settings"]:

            db["settings"][c_id] = {

                "max_warnings": 3,
                "antispam": False,
                "antilink": False,
                "antipromotion": False,
                "antiflood": False,
                "antibot": False,

                "welcome": False,
                "goodbye": False,
                "welcome_message": "",
                "goodbye_message": "",

                "ai_enabled": True,
                "games_enabled": True,
                "xp_enabled": True,
                "economy_enabled": True
            }

            need_save = True
        else:
            need_save = False

        result = db["settings"][c_id]

    if need_save:
        _schedule_save()

    return result


def update_group_setting(chat_id, setting, value):
    get_group_settings(chat_id)

    with _LOCK:
        db = _ensure_loaded()
        c_id = str(chat_id)
        db["settings"][c_id][setting] = value

    _schedule_save()

    return value


# ============================================================
# ANTI-SPAM / ANTI-LINK / ANTI-PROMOTION / ANTI-FLOOD / ANTI-BOT
# ============================================================

def toggle_antispam(chat_id, status: bool):
    return update_group_setting(chat_id, "antispam", status)


def is_antispam_enabled(chat_id):
    return get_group_settings(chat_id).get("antispam", False)


def toggle_antilink(chat_id, status: bool):
    return update_group_setting(chat_id, "antilink", status)


def is_antilink_enabled(chat_id):
    return get_group_settings(chat_id).get("antilink", False)


def toggle_antipromotion(chat_id, status: bool):
    return update_group_setting(chat_id, "antipromotion", status)


def is_antipromotion_enabled(chat_id):
    return get_group_settings(chat_id).get("antipromotion", False)


def toggle_antiflood(chat_id, status: bool):
    return update_group_setting(chat_id, "antiflood", status)


def is_antiflood_enabled(chat_id):
    return get_group_settings(chat_id).get("antiflood", False)


def toggle_antibot(chat_id, status: bool):
    return update_group_setting(chat_id, "antibot", status)


def is_antibot_enabled(chat_id):
    return get_group_settings(chat_id).get("antibot", False)


# ============================================================
# WELCOME / GOODBYE
# ============================================================

def toggle_welcome(chat_id, status: bool):
    return update_group_setting(chat_id, "welcome", status)


def toggle_goodbye(chat_id, status: bool):
    return update_group_setting(chat_id, "goodbye", status)


def set_welcome_message(chat_id, message):
    return update_group_setting(chat_id, "welcome_message", message)


def set_goodbye_message(chat_id, message):
    return update_group_setting(chat_id, "goodbye_message", message)


# ============================================================
# AI ENABLE / DISABLE
# ============================================================

def toggle_ai(chat_id, status: bool):
    return update_group_setting(chat_id, "ai_enabled", status)


def is_ai_enabled(chat_id):
    return get_group_settings(chat_id).get("ai_enabled", True)


# ============================================================
# GAMES
# ============================================================

def toggle_games(chat_id, status: bool):
    return update_group_setting(chat_id, "games_enabled", status)


def are_games_enabled(chat_id):
    return get_group_settings(chat_id).get("games_enabled", True)


# ============================================================
# XP SYSTEM
# ============================================================

def get_tier(xp):
    if xp < 500:
        return "Rookie"
    elif xp < 2000:
        return "Veteran"
    elif xp < 7000:
        return "Elite Warrior"
    elif xp < 15000:
        return "Bloody Commander"
    elif xp < 35000:
        return "Grandmaster"
    else:
        return "👑 Supreme Sovereign"


def update_user_activity(user_id, username, first_name, chat_id):
    with _LOCK:
        db = _ensure_loaded()

        u_id = str(user_id)
        c_id = str(chat_id)

        if u_id not in db["users"]:
            db["users"][u_id] = {
                "name": first_name,
                "username": username or "NoUser",
                "xp": 10,
                "global_messages": 0,
                "last_claim": "",
                "games_won": 0,
                "games_played": 0,
                "badge": "None",
                "chats": {},
                "achievements": [],
                "coins": 100,
                "wins": 0,
                "losses": 0
            }

        random_xp = random.randint(3, 15)

        db["users"][u_id]["xp"] += random_xp
        db["users"][u_id]["global_messages"] += 1
        db["users"][u_id]["name"] = first_name
        db["users"][u_id]["username"] = username or "NoUser"

        if c_id not in db["users"][u_id]["chats"]:
            db["users"][u_id]["chats"][c_id] = 0

        db["users"][u_id]["chats"][c_id] += 1

        if c_id not in db["group_stats"]:
            db["group_stats"][c_id] = {
                "messages": 0,
                "members_seen": [],
                "commands": 0,
                "games_played": 0
            }

        db["group_stats"][c_id]["messages"] += 1

        if u_id not in db["group_stats"][c_id]["members_seen"]:
            db["group_stats"][c_id]["members_seen"].append(u_id)

        result = (random_xp, db["users"][u_id]["xp"])

    _schedule_save()

    return result


def get_user_stats(user_id):
    with _LOCK:
        db = _ensure_loaded()
        stats = db["users"].get(str(user_id))
        # return a copy so callers can't mutate our in-memory state
        # by accident
        return json.loads(json.dumps(stats)) if stats is not None else None


# ============================================================
# BADGES
# ============================================================

def set_user_badge(user_id, badge_text):
    with _LOCK:
        db = _ensure_loaded()
        u_id = str(user_id)

        if u_id in db["users"]:
            db["users"][u_id]["badge"] = badge_text
            found = True
        else:
            found = False

    if found:
        _schedule_save()

    return found


# ============================================================
# LEADERBOARDS
# ============================================================

def get_master_leaderboards(chat_id):
    with _LOCK:
        db = _ensure_loaded()
        c_id = str(chat_id)

        global_list = sorted(
            db["users"].items(),
            key=lambda x: x[1].get("xp", 0),
            reverse=True
        )

        group_list = []

        for u_id, data in db["users"].items():
            if c_id in data.get("chats", {}):
                group_list.append((u_id, data))

        group_list = sorted(
            group_list,
            key=lambda x: x[1]["chats"].get(c_id, 0),
            reverse=True
        )

        # deep-copy so callers can't mutate in-memory state
        return (
            json.loads(json.dumps(global_list)),
            json.loads(json.dumps(group_list)),
        )


# ============================================================
# DAILY CLAIM
# ============================================================

def process_daily_claim(user_id):
    with _LOCK:
        db = _ensure_loaded()
        u_id = str(user_id)

        today = datetime.now().strftime("%Y-%m-%d")

        if u_id not in db["users"]:
            return "not_found", 0

        if db["users"][u_id].get("last_claim") == today:
            return "already_claimed", 0

        bonus_xp = random.randint(150, 450)

        db["users"][u_id]["xp"] += bonus_xp
        db["users"][u_id]["last_claim"] = today

    _schedule_save()

    return "success", bonus_xp


# ============================================================
# MANUAL XP
# ============================================================

def update_manual_xp(user_id, amount):
    with _LOCK:
        db = _ensure_loaded()
        u_id = str(user_id)

        if u_id in db["users"]:
            db["users"][u_id]["xp"] += amount

            if db["users"][u_id]["xp"] < 0:
                db["users"][u_id]["xp"] = 0

            new_xp = db["users"][u_id]["xp"]
        else:
            return 0

    _schedule_save()

    return new_xp


# ============================================================
# COINS / ECONOMY
# ============================================================

def get_coins(user_id):
    with _LOCK:
        db = _ensure_loaded()
        u_id = str(user_id)

        if u_id not in db["users"]:
            return 0

        return db["users"][u_id].get("coins", 100)


def update_coins(user_id, amount):
    with _LOCK:
        db = _ensure_loaded()
        u_id = str(user_id)

        if u_id not in db["users"]:
            return 0

        db["users"][u_id]["coins"] = max(
            0,
            db["users"][u_id].get("coins", 100) + amount
        )

        new_coins = db["users"][u_id]["coins"]

    _schedule_save()

    return new_coins


# ============================================================
# GAME STATISTICS
# ============================================================

def record_game(user_id, won=False):
    with _LOCK:
        db = _ensure_loaded()
        u_id = str(user_id)

        if u_id not in db["users"]:
            return

        db["users"][u_id]["games_played"] = (
            db["users"][u_id].get("games_played", 0) + 1
        )

        if won:
            db["users"][u_id]["games_won"] = (
                db["users"][u_id].get("games_won", 0) + 1
            )
            db["users"][u_id]["wins"] = (
                db["users"][u_id].get("wins", 0) + 1
            )
        else:
            db["users"][u_id]["losses"] = (
                db["users"][u_id].get("losses", 0) + 1
            )

    _schedule_save()


# ============================================================
# ACHIEVEMENTS
# ============================================================

def add_achievement(user_id, achievement):
    with _LOCK:
        db = _ensure_loaded()
        u_id = str(user_id)

        if u_id not in db["users"]:
            return False

        achievements = db["users"][u_id].setdefault("achievements", [])

        if achievement not in achievements:
            achievements.append(achievement)
            added = True
        else:
            added = False

    if added:
        _schedule_save()

    return added


def get_achievements(user_id):
    with _LOCK:
        db = _ensure_loaded()
        u_id = str(user_id)

        if u_id not in db["users"]:
            return []

        return list(db["users"][u_id].get("achievements", []))


# ============================================================
# RECOGNITION SYSTEM
# ============================================================

def set_recognition(user_id, first_name):
    with _LOCK:
        db = _ensure_loaded()

        db["active_recognition"][str(user_id)] = {
            "name": first_name,
            "expiry": datetime.now().timestamp() + 900
        }

    _schedule_save()


def check_recognition(user_id):
    with _LOCK:
        db = _ensure_loaded()
        u_id = str(user_id)

        if u_id not in db["active_recognition"]:
            return None

        current_time = datetime.now().timestamp()
        data = db["active_recognition"][u_id]

        if current_time < data["expiry"]:
            data["expiry"] = current_time + 900
            name = data["name"]
            need_save = True
        else:
            del db["active_recognition"][u_id]
            name = None
            need_save = True

    if need_save:
        _schedule_save()

    return name


# ============================================================
# WARNINGS
# ============================================================

def get_warnings(chat_id, user_id):
    with _LOCK:
        db = _ensure_loaded()
        return db["warnings"].get(f"{chat_id}_{user_id}", 0)


def add_warning(chat_id, user_id):
    with _LOCK:
        db = _ensure_loaded()
        key = f"{chat_id}_{user_id}"

        current = db["warnings"].get(key, 0) + 1
        db["warnings"][key] = current

    _schedule_save()

    return current


def clear_warnings(chat_id, user_id):
    with _LOCK:
        db = _ensure_loaded()
        key = f"{chat_id}_{user_id}"

        if key in db["warnings"]:
            db["warnings"][key] = 0
            need_save = True
        else:
            need_save = False

    if need_save:
        _schedule_save()


# ============================================================
# AI MEMORY
# ============================================================

def get_ai_memory(chat_id):
    with _LOCK:
        db = _ensure_loaded()
        chat_id = str(chat_id)

        if chat_id not in db["ai_memory"]:
            db["ai_memory"][chat_id] = []
            need_save = True
        else:
            need_save = False

        result = list(db["ai_memory"][chat_id])

    if need_save:
        _schedule_save()

    return result


def save_ai_message(chat_id, role, content, user_name=None):
    with _LOCK:
        db = _ensure_loaded()
        chat_id = str(chat_id)

        if chat_id not in db["ai_memory"]:
            db["ai_memory"][chat_id] = []

        message = {"role": role, "content": content}

        if user_name:
            message["user_name"] = user_name

        db["ai_memory"][chat_id].append(message)
        db["ai_memory"][chat_id] = db["ai_memory"][chat_id][-MAX_AI_MEMORY:]

    _schedule_save()


def clear_ai_memory(chat_id):
    with _LOCK:
        db = _ensure_loaded()
        db["ai_memory"][str(chat_id)] = []

    _schedule_save()


def get_ai_memory_for_cohere(chat_id):
    history = get_ai_memory(chat_id)

    messages = []

    for item in history:
        role = item.get("role")
        content = item.get("content", "")
        user_name = item.get("user_name")

        if role == "user" and user_name:
            content = f"{user_name}: {content}"

        messages.append({"role": role, "content": content})

    return messages


# ============================================================
# COOLDOWNS
# ============================================================

def set_cooldown(key, seconds):
    with _LOCK:
        db = _ensure_loaded()
        db["cooldowns"][key] = datetime.now().timestamp() + seconds

    _schedule_save()


def cooldown_active(key):
    with _LOCK:
        db = _ensure_loaded()
        expiry = db["cooldowns"].get(key, 0)
        current = datetime.now().timestamp()

        if current < expiry:
            return True

        if key in db["cooldowns"]:
            del db["cooldowns"][key]
            need_save = True
        else:
            need_save = False

    if need_save:
        _schedule_save()

    return False


# ============================================================
# GROUP STATISTICS
# ============================================================

def record_command(chat_id):
    with _LOCK:
        db = _ensure_loaded()
        c_id = str(chat_id)

        if c_id not in db["group_stats"]:
            db["group_stats"][c_id] = {
                "messages": 0,
                "members_seen": [],
                "commands": 0,
                "games_played": 0
            }

        db["group_stats"][c_id]["commands"] += 1

    _schedule_save()


def get_group_stats(chat_id):
    with _LOCK:
        db = _ensure_loaded()
        c_id = str(chat_id)

        stats = db["group_stats"].get(
            c_id,
            {
                "messages": 0,
                "members_seen": [],
                "commands": 0,
                "games_played": 0
            }
        )

        return json.loads(json.dumps(stats))


# ============================================================
# KNOWN CHATS REGISTRY
#
# Powers /broadcast: every group/supergroup the bot is currently
# in gets recorded here, so broadcasting doesn't require you to
# maintain a manual list. Entries are added the moment the bot
# joins a chat (or the first time it sees activity there) and
# removed the moment it's kicked/banned/leaves.
# ============================================================

def register_known_chat(chat_id, chat_type, title=None):
    with _LOCK:
        db = _ensure_loaded()
        db.setdefault("known_chats", {})
        c_id = str(chat_id)

        existing = db["known_chats"].get(c_id)

        if existing == {"type": chat_type, "title": title or ""}:
            return  # nothing changed, skip the write

        db["known_chats"][c_id] = {
            "type": chat_type,
            "title": title or "",
        }

    _schedule_save()


def remove_known_chat(chat_id):
    with _LOCK:
        db = _ensure_loaded()
        db.setdefault("known_chats", {})
        c_id = str(chat_id)

        if c_id in db["known_chats"]:
            del db["known_chats"][c_id]
            need_save = True
        else:
            need_save = False

    if need_save:
        _schedule_save()


def get_known_group_chats():
    """Returns a list of chat_id ints for every group/supergroup
    currently on record (used by /broadcast and the XP-gift drop)."""

    with _LOCK:
        db = _ensure_loaded()
        chats = db.get("known_chats", {})

        return [
            int(c_id)
            for c_id, info in chats.items()
            if info.get("type") in ("group", "supergroup")
        ]