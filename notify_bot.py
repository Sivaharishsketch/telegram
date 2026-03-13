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

# Stores pending quality selections: { chat_id: { "url": ..., "platform": ... } }
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


# ================= TELEGRAM HELPERS =================
def send_message(chat_id, text):
    r = requests.post(
        f"{TG_API}/sendMessage",
        data={"chat_id": chat_id, "text": text}
    ).json()
    return r["result"]["message_id"] if r.get("ok") else None


def edit_message(chat_id, msg_id, text):
    requests.post(
        f"{TG_API}/editMessageText",
        data={"chat_id": chat_id, "message_id": msg_id, "text": text}
    )


def send_keyboard(chat_id, text, keyboard):
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


# ================= DOWNLOAD =================
def cleanup(chat_id, platform):
    base = f"dl_{platform}_{chat_id}"
    for f in os.listdir("."):
        if f.startswith(base):
            try:
                os.remove(f)
            except Exception:
                pass


def download_and_send(chat_id, user, url, quality, platform):
    is_audio = quality == "audio"
    base_name = f"dl_{platform}_{chat_id}"
    out_template = f"{base_name}.%(ext)s"

    msg_id = send_message(chat_id, f"⬇️ Downloading ({quality})...")

    try:
        if is_audio:
            cmd = [
                "yt-dlp",
                "--no-playlist",
                "-x",
                "--audio-format", "mp3",
                "--audio-quality", "0",
                "-o", out_template,
                url,
            ]
        else:
            height = {"360p": 360, "720p": 720, "1080p": 1080}.get(quality, 720)
            # Simple reliable format — no complex ext filters
            fmt = f"bestvideo[height<={height}]+bestaudio/best[height<={height}]/best"
            cmd = [
                "yt-dlp",
                "--no-playlist",
                "-f", fmt,
                "--merge-output-format", "mp4",
                "-o", out_template,
                url,
            ]

        print(f"[CMD] {' '.join(cmd)}")
        result = subprocess.run(cmd, check=True, timeout=600,
                                capture_output=True, text=True)
        print(result.stdout[-500:] if result.stdout else "")

        # Find downloaded file
        candidates = sorted(
            [f for f in os.listdir(".") if f.startswith(base_name)],
            key=lambda f: os.path.getmtime(f),
            reverse=True,
        )
        if not candidates:
            raise FileNotFoundError("Downloaded file not found after yt-dlp")

        actual_file = candidates[0]
        size = os.path.getsize(actual_file)

        if size > MAX_UPLOAD_SIZE:
            edit_message(
                chat_id, msg_id,
                f"⚠️ File too large ({round(size / 1024 / 1024, 1)} MB)\n"
                "Cannot send files over 1 GB."
            )
        else:
            edit_message(chat_id, msg_id, "📤 Uploading...")
            send_document(chat_id, actual_file)
            edit_message(chat_id, msg_id, "✅ Done!")

        log(user, f"{platform.upper()}_{quality.upper()}", url)

    except subprocess.CalledProcessError as e:
        stderr = (e.stderr or "")[-300:]
        edit_message(chat_id, msg_id, f"❌ Download failed\n{stderr}")
        print(f"[yt-dlp ERROR] {stderr}")

    except subprocess.TimeoutExpired:
        edit_message(chat_id, msg_id, "❌ Timed out (10 min limit)")

    except Exception as e:
        edit_message(chat_id, msg_id, f"❌ Error: {str(e)[:200]}")
        print(f"[ERROR] {e}")

    finally:
        cleanup(chat_id, platform)


def ask_quality(chat_id, url, platform):
    label = "🎬 YouTube" if platform == "yt" else "📸 Instagram"
    keyboard = [
        [{"text": "🎵 Audio only (MP3)", "callback_data": f"dl|{platform}|audio"}],
        [
            {"text": "📹 360p",  "callback_data": f"dl|{platform}|360p"},
            {"text": "📹 720p",  "callback_data": f"dl|{platform}|720p"},
            {"text": "📹 1080p", "callback_data": f"dl|{platform}|1080p"},
        ],
    ]
    send_keyboard(chat_id, f"{label} link detected.\nChoose quality:", keyboard)
    pending_quality[chat_id] = {"url": url, "platform": platform}


# ================= MAIN LOOP =================
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

        # ===== CALLBACK (button press) =====
        if "callback_query" in upd:
            cb      = upd["callback_query"]
            cb_chat = cb["message"]["chat"]["id"]
            cb_msg  = cb["message"]["message_id"]
            cb_user = cb["from"]
            data    = cb.get("data", "")

            answer_callback(cb["id"])

            if data.startswith("dl|"):
                parts = data.split("|")
                if len(parts) == 3:
                    _, platform, quality = parts
                    pending = pending_quality.pop(cb_chat, None)

                    if pending is None:
                        send_message(cb_chat, "❌ Session expired. Please send the link again.")
                    else:
                        delete_message(cb_chat, cb_msg)
                        download_and_send(cb_chat, cb_user, pending["url"], quality, platform)
            continue

        # ===== NORMAL MESSAGE =====
        if "message" not in upd:
            continue

        msg     = upd["message"]
        chat_id = msg["chat"]["id"]
        user    = msg["from"]
        text    = msg.get("text", "")

        if text == "/start":
            notify_owner(user)
            log(user, "START", "")
            send_message(
                chat_id,
                "👋 Hi!\n\n"
                "What I can do:\n"
                "• 🎬 YouTube link → 360p / 720p / 1080p / Audio MP3\n"
                "• 📸 Instagram link → video/photo download\n"
                "• 📁 Forward any file → get direct download link\n\n"
                "⬆️ Max upload size: 1 GB"
            )
            continue

        if "document" in msg or "video" in msg:
            file_obj = msg.get("document") or msg.get("video")
            r = requests.get(
                f"{TG_API}/getFile",
                params={"file_id": file_obj["file_id"]}
            ).json()
            if not r.get("ok"):
                send_message(chat_id, "❌ Unable to get file info")
                continue
            link = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{r['result']['file_path']}"
            send_message(chat_id, f"⬇️ Direct download link:\n{link}")
            log(user, "FILE", link)
            continue

        if "youtube.com" in text or "youtu.be" in text:
            log(user, "YOUTUBE_LINK", text)
            ask_quality(chat_id, text.strip(), "yt")
            continue

        if "instagram.com" in text:
            log(user, "INSTAGRAM_LINK", text)
            ask_quality(chat_id, text.strip(), "ig")
            continue

        send_message(chat_id, "❌ Send a YouTube / Instagram link or forward a file.")

    time.sleep(1)
