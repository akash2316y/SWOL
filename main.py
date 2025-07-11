import pyrogram
from pyrogram import Client, filters
import asyncio
import os
import json
import time

# Load configuration
with open('config.json', 'r') as f:
    DATA = json.load(f)

def getenv(var):
    return os.environ.get(var) or DATA.get(var, None)

bot_token = getenv("TOKEN")
api_hash = getenv("HASH")
api_id = getenv("ID")
DB_CHANNEL = int(getenv("DB_CHANNEL"))

bot = Client("mybot", api_id=api_id, api_hash=api_hash, bot_token=bot_token)

ss = getenv("STRING")
if ss:
    acc = Client("myacc", api_id=api_id, api_hash=api_hash, session_string=ss)
    acc.start()
else:
    acc = None

ANIMATION_FRAMES = [".", "..", "..."]

def humanbytes(size):
    if not size:
        return "0B"
    power = 2**10
    n = 0
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    while size >= power and n < len(units) - 1:
        size /= power
        n += 1
    return f"{size:.2f} {units[n]}"

def time_formatter(milliseconds: int) -> str:
    seconds = int(milliseconds / 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h, {minutes}m"
    elif minutes:
        return f"{minutes}m, {seconds}s"
    else:
        return f"{seconds}s"

def progress_bar(current, total):
    percent = current * 100 / total
    bar_length = 10
    filled_length = int(percent / (100 / bar_length))
    bar = '▪️' * filled_length + '▫️' * (bar_length - filled_length)
    return bar, percent

async def progress(current, total, message, start, status_type, anim_step):
    now = time.time()
    elapsed = now - start
    speed = current / elapsed if elapsed > 0 else 0
    eta = (total - current) / speed if speed > 0 else 0

    bar, percent = progress_bar(current, total)
    dots = ANIMATION_FRAMES[anim_step[0] % len(ANIMATION_FRAMES)]

    text = f"""{status_type} {dots}

[{bar}]
Progress: {percent:.2f}%
Size: {humanbytes(current)} of {humanbytes(total)}
Speed: {humanbytes(speed)}/s
ETA: {time_formatter(eta * 1000)}"""

    try:
        await message.edit_text(text)
    except:
        pass

    anim_step[0] += 1

async def update_progress_every_3s(message, total, start, status_type, current_func):
    anim_step = [0]
    while True:
        current = current_func()
        await progress(current, total, message, start, status_type, anim_step)
        if current >= total:
            break
        await asyncio.sleep(3)

@bot.on_message(filters.command(["start"]))
async def start_command(client, message):
    await message.reply_text("👋 Hi! Send me any Telegram post link, and I'll try to download and forward it.")

@bot.on_message(filters.text)
async def main_handler(client, message):
    text = message.text

    if ("https://t.me/+" in text) or ("https://t.me/joinchat/" in text):
        if not acc:
            return
        try:
            await acc.join_chat(text)
        except:
            pass
        return

    if "https://t.me/" in text:
        parts = text.split("/")
        temp = parts[-1].replace("?single", "").split("-")

        try:
            from_id = int(temp[0].strip())
            to_id = int(temp[1].strip())
        except:
            from_id = to_id = int(temp[0].strip())

        for msgid in range(from_id, to_id + 1):
            if "https://t.me/c/" in text:
                chatid = int("-100" + parts[4])
                if not acc:
                    return
                await handle_private(message, chatid, msgid)
            else:
                username = parts[3]
                try:
                    msg = await bot.get_messages(username, msgid)
                except:
                    if not acc:
                        return
                    await handle_private(message, username, msgid)

            await asyncio.sleep(1)

async def handle_private(message, chatid, msgid):
    msg = await acc.get_messages(chatid, msgid)
    msg_type = get_message_type(msg)

    if msg_type == "Text":
        await acc.send_message(DB_CHANNEL, msg.text or "Empty Message", entities=msg.entities)
        return

    smsg = await message.reply_text("📥 Downloading...")

    start_time = time.time()
    current_downloaded = [0]

    async def download_progress(current, total):
        current_downloaded[0] = current  # Update latest downloaded size

    # Start background progress updater
    progress_task = asyncio.create_task(update_progress_every_3s(smsg, msg.document.file_size if msg.document else msg.video.file_size if msg.video else 0, start_time, "📥 Downloading", lambda: current_downloaded[0]))

    file = await acc.download_media(msg, progress=download_progress)
    current_downloaded[0] = os.path.getsize(file) if file and os.path.exists(file) else current_downloaded[0]

    progress_task.cancel()

    if not file:
        await smsg.edit_text("❌ Failed to download.")
        return

    start_upload = time.time()
    await smsg.edit_text("📤 Uploading...")
    current_uploaded = [0]

    async def upload_progress(current, total):
        current_uploaded[0] = current

    progress_task_upload = asyncio.create_task(update_progress_every_3s(smsg, os.path.getsize(file), start_upload, "📤 Uploading", lambda: current_uploaded[0]))

    try:
        sent_msg = None

        if msg_type == "Document":
            sent_msg = await acc.send_document(DB_CHANNEL, file, caption=msg.caption, caption_entities=msg.caption_entities, progress=upload_progress)
        elif msg_type == "Video":
            sent_msg = await acc.send_video(DB_CHANNEL, file, caption=msg.caption, caption_entities=msg.caption_entities, duration=msg.video.duration, width=msg.video.width, height=msg.video.height, progress=upload_progress)
        elif msg_type == "Audio":
            sent_msg = await acc.send_audio(DB_CHANNEL, file, caption=msg.caption, caption_entities=msg.caption_entities, progress=upload_progress)
        elif msg_type == "Photo":
            sent_msg = await acc.send_photo(DB_CHANNEL, file, caption=msg.caption, caption_entities=msg.caption_entities)
        elif msg_type == "Voice":
            sent_msg = await acc.send_voice(DB_CHANNEL, file, caption=msg.caption, caption_entities=msg.caption_entities, progress=upload_progress)
        elif msg_type == "Animation":
            sent_msg = await acc.send_animation(DB_CHANNEL, file)
        elif msg_type == "Sticker":
            sent_msg = await acc.send_sticker(DB_CHANNEL, file)

    except Exception as e:
        await smsg.edit_text(f"❌ Upload failed: {e}")
    finally:
        progress_task_upload.cancel()
        try:
            os.remove(file)
        except:
            pass
        await smsg.delete()

def get_message_type(msg):
    if msg.document: return "Document"
    if msg.video: return "Video"
    if msg.audio: return "Audio"
    if msg.photo: return "Photo"
    if msg.voice: return "Voice"
    if msg.animation: return "Animation"
    if msg.sticker: return "Sticker"
    if msg.text: return "Text"
    return None

bot.run()
