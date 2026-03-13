import requests
import time
import os
import json
import subprocess
from datetime import datetime

import gspread
from oauth2client.service_account import ServiceAccountCredentials

# ================= ENV =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID"))
SHEET_ID = os.getenv("SHEET_ID")
GOOGLE_CREDS_RAW = os.getenv("GOOGLE_CREDENTIALS")

if not all([BOT_TOKEN, OWNER_ID, SHEET_ID, GOOGLE_CREDS_RAW]):
    raise RuntimeError("❌ Missing environment variables")

TG_API = f"https://api.telegram.org/bot{BOT_TOKEN}"
last_update_id = 0

MAX_UPLOAD_SIZE = 1024 * 1024 * 1024  # 1GB

# ================= PENDING QUALITY SELECTIONS =================
# Stores { chat_id: { "url": "...", "type": "youtube" } }
pending_quality = {}

# ================= GOOGLE SHEETS =================
scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

creds = ServiceAccountCredentials.from_json_keyfile_dict(
    json.loads(GOOGLE_CREDS_RAW), scope
)
gc = gspread.authorize(creds)
sheet = gc.open_by_key(SHEET_ID)

try:
    ws = sheet.worksheet("telegram")
except Exception:
    ws = sheet.add_worksheet("telegram", 1000, 10)
    ws.append_row(["Time", "Name", "Username", "UserID", "Action", "Content"])


# ================= HELPERS =================
def send_message(chat_id, text):
    r = requests.post(
        f"{TG_API}/sendMessage",
        data={"chat_id": chat_id, "text": text}
    ).json()
    return r["result"]["message_id"] if r.get("ok") else None


def edit_message(chat_id, msg_id, text):
    requests.post(
        f"{TG_API}/editMessageText",
        data={
            "chat_id": chat_id,
            "message_id": msg_id,
            "text": text,
        }
    )


def send_message_with_keyboard(chat_id, text, keyboard):
    """Send a message with an inline keyboard."""
    r = requests.post(
        f"{TG_API}/sendMessage",
        json={
            "chat_id": chat_id,
            "text": text,
            "reply_markup": {"inline_keyboard": keyboard},
        }
    ).json()
    return r["result"]["message_id"] if r.get("ok") else None


def answer_callback(callback_query_id):
    requests.post(
        f"{TG_API}/answerCallbackQuery",
        data={"callback_query_id": callback_query_id}
    )


def delete_message(chat_id, msg_id):
    requests.post(
        f"{TG_API}/deleteMessage",
        data={"chat_id": chat_id, "message_id": msg_id}
    )


def send_document(chat_id, file_path):
    with open(file_path, "rb") as f:
        requests.post(
            f"{TG_API}/sendDocument",
            data={"chat_id": chat_id},
            files={"document": f}
        )


def log(user, action, content):
    ws.append_row([
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        user.get("first_name", ""),
        user.get("username", ""),
        user.get("id"),
        action,
        content,
    ])


def notify_owner(user):
    send_message(
        OWNER_ID,
        f"👤 New user\n\n"
        f"Name: {user.get('first_name')}\n"
        f"Username: @{user.get('username', 'N/A')}\n"
        f"User ID: {user['id']}"
    )


# ================= DOWNLOAD HELPERS =================
def yt_format_string(quality: str) -> str:
    """
    Returns yt-dlp format string based on quality choice.
    quality: '360p', '720p', '1080p', 'audio'
    """
    if quality == "audio":
        return "bestaudio/best"
    height_map = {"360p": 360, "720p": 720, "1080p": 1080}
    h = height_map.get(quality, 720)
    # Prefer mp4, fallback to best under height, merge audio
    return f"bv*[height<={h}][ext=mp4]+ba[ext=m4a]/bv*[height<={h}]+ba/best[height<={h}]/best"


def download_and_send(chat_id, user, url, quality, platform):
    """Download via yt-dlp and send to user. quality: '360p'/'720p'/'1080p'/'audio'"""
    is_audio = quality == "audio"
    ext = "mp3" if is_audio else "mp4"
    out_template = f"dl_{platform}_{chat_id}.%(ext)s"
    out_final = f"dl_{platform}_{chat_id}.{ext}"

    msg_id = send_message(chat_id, f"⬇️ Downloading ({quality})...")

    try:
        cmd = [
            "yt-dlp",
            "-f", yt_format_string(quality),
            "--no-playlist",
            "-o", out_template,
        ]

        if is_audio:
            cmd += [
                "--extract-audio",
                "--audio-format", "mp3",
                "--audio-quality", "0",
            ]
        else:
            # Force merge into mp4 container, avoid GIF/webm issues
            cmd += [
                "--merge-output-format", "mp4",
                "--recode-video", "mp4",
            ]

        cmd.append(url)
        subprocess.run(cmd, check=True, timeout=600)

        # yt-dlp might name it differently — find the file
        actual_file = out_final
        if not os.path.exists(actual_file):
            # Search for any file matching the template base
            base = f"dl_{platform}_{chat_id}"
            candidates = [f for f in os.listdir(".") if f.startswith(base)]
            if candidates:
                actual_file = candidates[0]
            else:
                raise FileNotFoundError("Downloaded file not found")

        size = os.path.getsize(actual_file)

        if size > MAX_UPLOAD_SIZE:
            edit_message(
                chat_id, msg_id,
                f"⚠️ File too large ({round(size/1024/1024, 1)} MB)\n"
                "Cannot upload files over 1 GB."
            )
        else:
            edit_message(chat_id, msg_id, "📤 Uploading...")
            send_document(chat_id, actual_file)
            edit_message(chat_id, msg_id, "✅ Done!")

        log(user, f"{platform.upper()}_{quality.upper()}", url)
        os.remove(actual_file)

    except subprocess.TimeoutExpired:
        edit_message(chat_id, msg_id, "❌ Download timed out (10 min limit)")
    except Exception as e:
        edit_message(chat_id, msg_id, f"❌ Download failed\n{str(e)[:200]}")
        print(f"[ERROR] {platform} download: {e}")
        # Cleanup any partial files
        base = f"dl_{platform}_{chat_id}"
        for f in os.listdir("."):
            if f.startswith(base):
                try:
                    os.remove(f)
                except Exception:
                    pass


def ask_quality(chat_id, url, platform):
    """Show quality selection keyboard and store pending URL."""
    keyboard = [
        [
            {"text": "🎵 Audio only (MP3)", "callback_data": f"dl|{platform}|audio"},
        ],
        [
            {"text": "📹 360p",  "callback_data": f"dl|{platform}|360p"},
            {"text": "📹 720p",  "callback_data": f"dl|{platform}|720p"},
            {"text": "📹 1080p", "callback_data": f"dl|{platform}|1080p"},
        ],
    ]
    msg_id = send_message_with_keyboard(
        chat_id,
        f"{'🎬 YouTube' if platform == 'yt' else '📸 Instagram'} link detected.\n"
        "Choose quality / format:",
        keyboard,
    )
    pending_quality[chat_id] = {"url": url, "platform": platform, "kbd_msg_id": msg_id}


# ================= BOT LOOP =================
print("🤖 Bot started")

while True:
    try:
        updates = requests.get(
            f"{TG_API}/getUpdates",
            params={"offset": last_update_id + 1, "timeout": 30},
            timeout=35,
        ).json()
    except Exception as e:
        print(f"[POLL ERROR] {e}")
        time.sleep(2)
        continue

    if not updates.get("ok"):
        time.sleep(2)
        continue

    for upd in updates["result"]:
        last_update_id = upd["update_id"]

        # ===== CALLBACK QUERY (inline button press) =====
        if "callback_query" in upd:
            cb = upd["callback_query"]
            cb_id = cb["id"]
            cb_chat_id = cb["message"]["chat"]["id"]
            cb_msg_id = cb["message"]["message_id"]
            cb_user = cb["from"]
            data = cb.get("data", "")

            answer_callback(cb_id)

            if data.startswith("dl|"):
                _, platform, quality = data.split("|", 2)
                pending = pending_quality.pop(cb_chat_id, None)

                if pending is None:
                    send_message(cb_chat_id, "❌ Session expired. Please send the link again.")
                    continue

                # Remove the quality keyboard message
                delete_message(cb_chat_id, cb_msg_id)

                download_and_send(cb_chat_id, cb_user, pending["url"], quality, platform)

            continue

        # ===== NORMAL MESSAGE =====
        if "message" not in upd:
            continue

        msg = upd["message"]
        chat_id = msg["chat"]["id"]
        user = msg["from"]
        text = msg.get("text", "")

        # ===== START =====
        if text == "/start":
            notify_owner(user)
            log(user, "START", "")
            send_message(
                chat_id,
                "👋 Hi!\n\n"
                "What I can do:\n"
                "• 🎬 YouTube link → choose quality (360p / 720p / 1080p) or audio-only MP3\n"
                "• 📸 Instagram link → download video/photo\n"
                "• 📁 Forward any file → get direct download link\n\n"
                "⬆️ Supports uploads up to 1 GB"
            )
            continue

        # ===== FILE (forward) =====
        if "document" in msg or "video" in msg:
            file_obj = msg.get("document") or msg.get("video")
            file_id = file_obj["file_id"]

            r = requests.get(
                f"{TG_API}/getFile",
                params={"file_id": file_id}
            ).json()

            if not r.get("ok"):
                send_message(chat_id, "❌ Unable to get file info")
                continue

            path = r["result"]["file_path"]
            link = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{path}"
            send_message(chat_id, f"⬇️ Direct download link:\n{link}")
            log(user, "FILE", link)
            continue

        # ===== YOUTUBE =====
        if "youtube.com" in text or "youtu.be" in text:
            log(user, "YOUTUBE_LINK", text)
            ask_quality(chat_id, text.strip(), "yt")
            continue

        # ===== INSTAGRAM =====
        if "instagram.com" in text:
            log(user, "INSTAGRAM_LINK", text)
            ask_quality(chat_id, text.strip(), "ig")
            continue

        send_message(chat_id, "❌ Send a YouTube / Instagram link or forward a file.")

    time.sleep(1)
