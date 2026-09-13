# ============================================================
# handlers_media.py
# BLOODY MD — MEDIA GENERATION + SEARCH HANDLERS
#
# /imagine <prompt>     -> AI-generated image (Pollinations, free, no key)
# /img <description>    -> Real photo matching description (Pexels/Pixabay)
# /vid <description>    -> Real video matching description (Pexels/Pixabay)
#
# All network calls use aiohttp so nothing blocks the event loop.
# No asyncio.to_thread needed here since aiohttp is natively async.
# ============================================================

import os
import random
import urllib.parse

import aiohttp

# ============================================================
# CONFIG — put these in your .env / environment
# ============================================================

PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY")
PIXABAY_API_KEY = os.environ.get("PIXABAY_API_KEY")

if not PEXELS_API_KEY or not PIXABAY_API_KEY:
    from config import PEXELS_API_KEY, PIXABAY_API_KEY
# Shared session, created once and reused (avoids opening a new
# TCP connection pool on every single request).
_SESSION = None


async def get_session():
    global _SESSION
    if _SESSION is None or _SESSION.closed:
        _SESSION = aiohttp.ClientSession()
    return _SESSION


# ============================================================
# /imagine — AI image generation (Pollinations.ai, free, no API key)
# ============================================================

async def imagine_command(update, context):
    message = update.effective_message

    if not context.args:
        await message.reply_text(
            "🎨 Usage: `/imagine <description>`\n"
            "Example: `/imagine a red dragon flying over Lagos at sunset`",
            parse_mode="Markdown"
        )
        return

    prompt = " ".join(context.args).strip()

    status_msg = await message.reply_text(
        f"🎨 Generating image for: *{prompt}*...",
        parse_mode="Markdown"
    )

    try:
        encoded_prompt = urllib.parse.quote(prompt)
        # seed=random keeps repeated prompts from returning a cached
        # identical image every time
        seed = random.randint(1, 999999)
        url = (
            f"https://image.pollinations.ai/prompt/{encoded_prompt}"
            f"?width=1024&height=1024&seed={seed}&nologo=true"
        )

        session = await get_session()

        async with session.get(url, timeout=aiohttp.ClientTimeout(total=60)) as resp:
            if resp.status != 200:
                raise RuntimeError(f"Pollinations returned {resp.status}")

            image_bytes = await resp.read()

        await context.bot.send_photo(
            chat_id=message.chat_id,
            photo=image_bytes,
            caption=f"🎨 **{prompt}**\n\n🩸 BLOODY MD IMAGINE",
            parse_mode="Markdown"
        )

        await status_msg.delete()

    except Exception as error:
        print(f"/imagine error: {error}")
        try:
            await status_msg.edit_text(
                "❌ Image generation failed. Try again in a moment."
            )
        except Exception:
            pass


# ============================================================
# /img — search + download a real photo matching a description
# ============================================================

async def img_command(update, context):
    message = update.effective_message

    if not context.args:
        await message.reply_text(
            "🖼️ Usage: `/img <description>`\n"
            "Example: `/img mountain landscape`",
            parse_mode="Markdown"
        )
        return

    query = " ".join(context.args).strip()
    status_msg = await message.reply_text(f"🔎 Searching photos for: *{query}*...", parse_mode="Markdown")

    try:
        photo_url = await _search_photo(query)

        if not photo_url:
            await status_msg.edit_text(f"❌ No photos found for **{query}**.", parse_mode="Markdown")
            return

        await context.bot.send_photo(
            chat_id=message.chat_id,
            photo=photo_url,
            caption=f"🖼️ **{query}**",
            parse_mode="Markdown"
        )
        await status_msg.delete()

    except Exception as error:
        print(f"/img error: {error}")
        try:
            await status_msg.edit_text("❌ Photo search failed.")
        except Exception:
            pass


async def _search_photo(query):
    session = await get_session()

    # Try Pexels first
    if PEXELS_API_KEY:
        url = f"https://api.pexels.com/v1/search?query={urllib.parse.quote(query)}&per_page=10"
        headers = {"Authorization": PEXELS_API_KEY}

        async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=20)) as resp:
            if resp.status == 200:
                data = await resp.json()
                photos = data.get("photos", [])
                if photos:
                    chosen = random.choice(photos)
                    return chosen["src"]["large"]

    # Fall back to Pixabay
    if PIXABAY_API_KEY:
        url = (
            f"https://pixabay.com/api/?key={PIXABAY_API_KEY}"
            f"&q={urllib.parse.quote(query)}&image_type=photo&per_page=10"
        )

        async with session.get(url, timeout=aiohttp.ClientTimeout(total=20)) as resp:
            if resp.status == 200:
                data = await resp.json()
                hits = data.get("hits", [])
                if hits:
                    chosen = random.choice(hits)
                    return chosen["largeImageURL"]

    return None


# ============================================================
# /vid — search + download a real video matching a description
# ============================================================

async def vid_command(update, context):
    message = update.effective_message

    if not context.args:
        await message.reply_text(
            "🎬 Usage: `/vid <description>`\n"
            "Example: `/vid ocean waves`",
            parse_mode="Markdown"
        )
        return

    query = " ".join(context.args).strip()
    status_msg = await message.reply_text(f"🔎 Searching videos for: *{query}*...", parse_mode="Markdown")

    try:
        video_url = await _search_video(query)

        if not video_url:
            await status_msg.edit_text(f"❌ No videos found for **{query}**.", parse_mode="Markdown")
            return

        await status_msg.edit_text(f"📤 Uploading video for **{query}**...", parse_mode="Markdown")

        session = await get_session()
        async with session.get(video_url, timeout=aiohttp.ClientTimeout(total=120)) as resp:
            video_bytes = await resp.read()

        await context.bot.send_video(
            chat_id=message.chat_id,
            video=video_bytes,
            caption=f"🎬 **{query}**",
            parse_mode="Markdown",
            read_timeout=180,
            write_timeout=180,
        )
        await status_msg.delete()

    except Exception as error:
        print(f"/vid error: {error}")
        try:
            await status_msg.edit_text("❌ Video search/upload failed.")
        except Exception:
            pass


async def _search_video(query):
    session = await get_session()

    # Try Pexels first
    if PEXELS_API_KEY:
        url = f"https://api.pexels.com/videos/search?query={urllib.parse.quote(query)}&per_page=10"
        headers = {"Authorization": PEXELS_API_KEY}

        async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=20)) as resp:
            if resp.status == 200:
                data = await resp.json()
                videos = data.get("videos", [])
                if videos:
                    chosen = random.choice(videos)
                    # pick a reasonably small file (avoid huge 4K files)
                    files = sorted(chosen["video_files"], key=lambda f: f.get("width", 0))
                    for f in files:
                        if f.get("width", 0) and f["width"] <= 1280:
                            return f["link"]
                    return files[0]["link"] if files else None

    # Fall back to Pixabay
    if PIXABAY_API_KEY:
        url = f"https://pixabay.com/api/videos/?key={PIXABAY_API_KEY}&q={urllib.parse.quote(query)}&per_page=10"

        async with session.get(url, timeout=aiohttp.ClientTimeout(total=20)) as resp:
            if resp.status == 200:
                data = await resp.json()
                hits = data.get("hits", [])
                if hits:
                    chosen = random.choice(hits)
                    videos = chosen.get("videos", {})
                    # "medium" is a good balance of quality/size
                    return (videos.get("medium") or videos.get("small") or {}).get("url")

    return None


# ============================================================
# CLEANUP — call this from your bot's shutdown handler
# ============================================================

async def close_media_session():
    global _SESSION
    if _SESSION and not _SESSION.closed:
        await _SESSION.close()