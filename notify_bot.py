import os
import subprocess
import requests
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, ContextTypes, filters

BOT_TOKEN = os.getenv("BOT_TOKEN")

DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# ---------- COMMON SEND ----------
async def send_file(update, file_path, caption="✅ Downloaded"):
    size_mb = os.path.getsize(file_path) / (1024 * 1024)

    if size_mb > 49:
        await update.message.reply_text("❌ File too large for Telegram")
        return

    with open(file_path, "rb") as f:
        await update.message.reply_document(f, caption=caption)

    os.remove(file_path)


# ---------- YOUTUBE ----------
async def youtube_download(update, url):
    await update.message.reply_text("⬇️ YouTube downloading...")

    output = f"{DOWNLOAD_DIR}/%(title).50s.%(ext)s"
    cmd = [
        "yt-dlp",
        "-f", "bv*[height<=720]+ba/b",
        "--merge-output-format", "mp4",
        "--no-playlist",
        "-o", output,
        url
    ]

    subprocess.run(cmd, check=True)
    file = sorted(os.listdir(DOWNLOAD_DIR))[-1]
    await send_file(update, f"{DOWNLOAD_DIR}/{file}", "🎬 YouTube Downloaded")


# ---------- INSTAGRAM ----------
async def instagram_download(update, url):
    await update.message.reply_text("⬇️ Instagram downloading...")

    output = f"{DOWNLOAD_DIR}/%(title).50s.%(ext)s"
    cmd = [
        "yt-dlp",
        "--no-playlist",
        "-o", output,
        url
    ]

    subprocess.run(cmd, check=True)
    file = sorted(os.listdir(DOWNLOAD_DIR))[-1]
    await send_file(update, f"{DOWNLOAD_DIR}/{file}", "📸 Instagram Downloaded")


# ---------- DIRECT LINK ----------
async def direct_download(update, url):
    await update.message.reply_text("⬇️ Downloading file...")

    filename = url.split("/")[-1].split("?")[0]
    file_path = f"{DOWNLOAD_DIR}/{filename}"

    r = requests.get(url, stream=True, timeout=60)
    r.raise_for_status()

    with open(file_path, "wb") as f:
        for chunk in r.iter_content(1024 * 1024):
            f.write(chunk)

    await send_file(update, file_path, "📁 File Downloaded")


# ---------- MAIN HANDLER ----------
async def handle_links(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()

    try:
        if "youtu" in url:
            await youtube_download(update, url)

        elif "instagram.com" in url:
            await instagram_download(update, url)

        elif url.startswith("http"):
            await direct_download(update, url)

        else:
            await update.message.reply_text("❌ Unsupported link")

    except Exception as e:
        await update.message.reply_text(f"❌ Failed\n\n{str(e)}")


# ---------- START ----------
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_links))
    app.run_polling()

if __name__ == "__main__":
    main()