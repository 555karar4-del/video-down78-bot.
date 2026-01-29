import os
import asyncio
import logging
import tempfile
import subprocess
import requests
from pathlib import Path
from urllib.parse import urlparse
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    CallbackQueryHandler,
)
import yt_dlp
import ffmpeg

# Logging setup
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

print("بدء التنفيذ: Imports جارية...")

# Update yt-dlp
try:
    subprocess.run(["yt-dlp", "-U"], check=True, capture_output=True, timeout=30)
    print("yt-dlp تم تحديثه")
except Exception as e:
    print(f"فشل تحديث yt-dlp: {e}")

# Check ffmpeg
print("جاري التحقق من ffmpeg...")
try:
    result = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True, timeout=5)
    if result.returncode == 0:
        print("ffmpeg موجود ✓ " + result.stdout.splitlines()[0])
    else:
        print("ffmpeg خطأ: " + result.stderr.strip())
except FileNotFoundError:
    print("ffmpeg غير موجود!")
except Exception as e:
    print(f"خطأ ffmpeg: {e}")

TOKEN = "8352548859:AAGxEI9yk_4TZwHO9UFZ5A7AhNU3YlvD2hQ"
OWNER_ID = 6538981552
MAX_FILE_SIZE = 50 * 1024 * 1024

print("الإعدادات تم تحميلها")

async def download_video(url: str, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    message = update.effective_message

    progress_msg = await message.reply_text("جاري المعالجة... ⏳")

    ydl_opts = {
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/bestvideo+bestaudio/best',
        'outtmpl': '',
        'quiet': True,
        'no_warnings': True,
        'noplaylist': True,
        'impersonate': 'chrome131',
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
            'Referer': 'https://www.google.com/',
        },
        'retries': 15,
        'fragment_retries': 10,
        'continuedl': True,
        'force_generic_extractor': True,
    }

    temp_dir = tempfile.mkdtemp()
    try:
        ydl_opts['outtmpl'] = os.path.join(temp_dir, '%(title)s.%(ext)s')

        filename = None
        info = None

        # Pixeldrain fallback
        if "pixeldrain.com" in url.lower():
            try:
                direct_url = url.replace("/api/file/", "/u/")
                r = requests.get(direct_url, stream=True, timeout=60, headers=ydl_opts['http_headers'])
                if r.status_code == 200:
                    content_type = r.headers.get("Content-Type", "")
                    ext = ".mp4" if "video" in content_type else ".file"
                    filename = f"pixeldrain_download{ext}"
                    full_path = os.path.join(temp_dir, filename)
                    with open(full_path, "wb") as f:
                        for chunk in r.iter_content(chunk_size=8192):
                            if chunk:
                                f.write(chunk)
                    print("تم التنزيل المباشر من Pixeldrain")
                else:
                    raise Exception(f"status {r.status_code}")
            except Exception as err:
                logger.warning(f"Fallback Pixeldrain فشل: {err}")

        # yt-dlp main
        if filename is None:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = await asyncio.to_thread(ydl.extract_info, url, download=True)
                filename = ydl.prepare_filename(info)

        if filename is None:
            raise Exception("لم يتم الحصول على اسم الملف")

        file_size = os.path.getsize(filename)

        # ضغط إذا كبير
        if file_size > MAX_FILE_SIZE:
            await progress_msg.edit_text("الملف كبير → جاري الضغط...")
            compressed = await compress_video(filename, temp_dir)
            if compressed:
                filename = compressed
                file_size = os.path.getsize(filename)

        # إعداد caption
        extractor = info.get('extractor_key', 'غير معروف') if info else 'Pixeldrain'
        title = info.get('title', 'ملف بدون عنوان') if info else 'ملف من Pixeldrain'
        caption = f"🎬 {title}\n• منصة: {extractor}\n• بواسطة @{context.bot.username}"

        if file_size <= MAX_FILE_SIZE:
            await context.bot.send_video(
                chat_id=chat_id,
                video=open(filename, "rb"),
                caption=caption,
                supports_streaming=True,
                reply_to_message_id=message.message_id,
            )
        else:
            await context.bot.send_document(
                chat_id=chat_id,
                document=open(filename, "rb"),
                caption=caption + "\n(كملف لأن الحجم كبير)",
                reply_to_message_id=message.message_id,
            )

        await progress_msg.delete()

    except Exception as e:
        error_str = str(e).lower()
        if any(word in error_str for word in ["private", "login", "restricted", "age"]):
            await progress_msg.edit_text("المحتوى خاص أو يتطلب تسجيل دخول.")
        elif "no video" in error_str or "no formats" in error_str or "cannot parse" in error_str:
            await progress_msg.edit_text("لا يمكن استخراج الفيديو. جرب رابط آخر.")
        elif "geo" in error_str or "blocked" in error_str:
            await progress_msg.edit_text("محتوى مقيد جغرافياً.")
        else:
            await progress_msg.edit_text(f"خطأ: {str(e)[:150]}...")
        logger.error(f"خطأ في {url}: {str(e)}", exc_info=True)

    finally:
        try:
            for file in Path(temp_dir).glob("*"):
                file.unlink(missing_ok=True)
            os.rmdir(temp_dir)
        except Exception as cleanup_err:
            logger.warning(f"تنظيف فشل: {cleanup_err}")


async def compress_video(input_path: str, temp_dir: str) -> str | None:
    output_path = os.path.join(temp_dir, "compressed.mp4")
    try:
        stream = ffmpeg.input(input_path)
        stream = ffmpeg.output(
            stream,
            output_path,
            vcodec="libx264",
            crf=28,
            preset="veryfast",
            acodec="aac",
            threads=0,
        )
        await asyncio.to_thread(ffmpeg.run, stream, overwrite_output=True, quiet=True)

        if os.path.exists(output_path) and os.path.getsize(output_path) > 100000:
            return output_path
        return None
    except Exception as e:
        logger.error(f"فشل الضغط: {e}")
        return None


# الهاندلرز (باقي الكود نفسه بدون تغيير)
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("كيفية الاستخدام ℹ️", callback_data="help")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "مرحباً كرار! 👋\nأرسل أي رابط وسأحاول تحميله\nTikTok • Instagram • YouTube • Facebook • Pixeldrain ...\nجرب الآن 🚀",
        reply_markup=reply_markup,
    )


async def help_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    text = "1. انسخ الرابط\n2. ألصقه هنا\n3. انتظر التنزيل\nالمحتوى الخاص قد لا يعمل."
    await query.edit_message_text(text)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text.startswith(("http://", "https://")):
        return
    url = text
    await download_video(url, update, context)


async def owner_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    await update.message.reply_text(f"شغال ✅ | مالك: {OWNER_ID} | {datetime.now().strftime('%Y-%m-%d %H:%M')}")


def main():
    print("دخول main()")
    if not TOKEN or ":" not in TOKEN:
        print("توكن خاطئ")
        return

    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stats", owner_stats))
    app.add_handler(CallbackQueryHandler(help_callback, pattern="^help$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("Polling بدأ")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
