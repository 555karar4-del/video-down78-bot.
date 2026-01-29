import os
import asyncio
import logging
import tempfile
import subprocess
import requests
from pathlib import Path
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

# لا نحدث yt-dlp تلقائياً بهذه الطريقة (غير موثوق في معظم المنصات)
print("yt-dlp version:", yt_dlp.version.__version__)

# فحص ffmpeg
print("جاري التحقق من ffmpeg...")
try:
    result = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True, timeout=6)
    if result.returncode == 0:
        print("ffmpeg موجود ✓ " + result.stdout.splitlines()[0])
    else:
        print("ffmpeg خطأ: " + result.stderr.strip())
except Exception as e:
    print(f"مشكلة ffmpeg: {e}")

TOKEN = "8352548859:AAGxEI9yk_4TZwHO9UFZ5A7AhNU3YlvD2hQ"
OWNER_ID = 6538981552
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 ميجا (حد تيليجرام للبوتات العادية)

print("الإعدادات تم تحميلها")


async def download_video(url: str, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    message = update.effective_message

    progress = await message.reply_text("جاري المعالجة... ⏳ (0%)")

    ydl_opts = {
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'outtmpl': '',
        'quiet': True,
        'no_warnings': True,
        'noplaylist': True,
        'continuedl': True,
        'retries': 10,
        'fragment_retries': 10,
        'socket_timeout': 35,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
            'Referer': 'https://www.google.com/',
        },
    }

    with tempfile.TemporaryDirectory() as temp_dir:
        try:
            ydl_opts['outtmpl'] = os.path.join(temp_dir, '%(title).180s.%(ext)s')

            filename = None
            info_dict = None

            # محاولة Pixeldrain مباشرة (طريقة أكثر استقراراً 2025)
            if "pixeldrain.com" in url.lower():
                file_id = url.split("/")[-1].split("?")[0]
                direct_url = f"https://cdn.pixeldrain.com/u/{file_id}"
                try:
                    r = requests.get(direct_url, stream=True, timeout=90, headers=ydl_opts['http_headers'])
                    if r.status_code == 200:
                        ext = ".mp4" if "video" in r.headers.get("Content-Type", "") else ".file"
                        filename = os.path.join(temp_dir, f"pixeldrain_{file_id}{ext}")
                        with open(filename, "wb") as f:
                            for chunk in r.iter_content(chunk_size=8192):
                                f.write(chunk)
                        print(f"تم تنزيل مباشر Pixeldrain → {filename}")
                except Exception as pix_err:
                    logger.warning(f"Pixeldrain fallback فشل: {pix_err}")

            # yt-dlp الرئيسي
            if not filename:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info_dict = await asyncio.to_thread(ydl.extract_info, url, download=True)
                    filename = ydl.prepare_filename(info_dict)

            if not filename or not os.path.exists(filename):
                raise Exception("لم يتم تنزيل الملف")

            # التأكد من أن الامتداد mp4 (مهم لـ send_video)
            if not filename.lower().endswith('.mp4'):
                new_filename = filename.rsplit('.', 1)[0] + '.mp4'
                try:
                    stream = ffmpeg.input(filename)
                    stream = ffmpeg.output(stream, new_filename, c='copy', movflags='faststart')
                    await asyncio.to_thread(ffmpeg.run, stream, overwrite_output=True, quiet=True)
                    if os.path.exists(new_filename):
                        os.remove(filename)
                        filename = new_filename
                except:
                    pass  # إذا فشل → نرسل كما هو

            file_size = os.path.getsize(filename)

            # ضغط إذا تجاوز الحد
            if file_size > MAX_FILE_SIZE:
                await progress.edit_text("الملف كبير (>50MB) → جاري الضغط...")
                compressed = await compress_video(filename, temp_dir)
                if compressed:
                    filename = compressed
                    file_size = os.path.getsize(filename)

            # إعداد النص
            extractor = info_dict.get('extractor_key', 'مباشر') if info_dict else 'Pixeldrain'
            title = info_dict.get('title', 'فيديو بدون عنوان') if info_dict else Path(filename).stem
            caption = f"🎥 {title[:180]}\n• منصة: {extractor}\n• بواسطة @{context.bot.username}"

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
                    caption=caption + "\n(كملف – الحجم كبير بعد الضغط)",
                    reply_to_message_id=message.message_id,
                )

            await progress.delete()

        except Exception as e:
            err = str(e).lower()
            if any(x in err for x in ["private", "login", "restricted", "age", "unavailable"]):
                text = "المحتوى خاص / مقيد / يحتاج تسجيل دخول."
            elif any(x in err for x in ["no video", "no formats", "cannot parse"]):
                text = "لا يمكن استخراج الفيديو من الرابط."
            elif any(x in err for x in ["geo", "blocked", "unavailable in your country"]):
                text = "المحتوى مقيد جغرافياً."
            else:
                text = f"خطأ: {str(e)[:140]}..."
            await progress.edit_text(text)
            logger.error(f"خطأ في {url}: {e}", exc_info=True)


async def compress_video(input_path: str, temp_dir: str) -> str | None:
    output_path = os.path.join(temp_dir, "compressed.mp4")
    try:
        process = (
            ffmpeg
            .input(input_path)
            .output(
                output_path,
                vcodec="libx264",
                crf=28,
                preset="veryfast",
                acodec="aac",
                threads=0,
                movflags="faststart"
            )
            .overwrite_output()
            .run_async(pipe_stderr=True)
        )

        await asyncio.to_thread(process.wait)

        if process.returncode == 0 and os.path.exists(output_path):
            size = os.path.getsize(output_path)
            if size > 300_000:  # تجنب ملفات فاشلة/فارغة
                return output_path
        return None

    except Exception as e:
        logger.error(f"فشل الضغط: {e}")
        return None


# ────────────────────────────────────────
# باقي الدوال بدون تغيير كبير
# ────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("كيفية الاستخدام ℹ️", callback_data="help")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "مرحباً كرار! 👋\nأرسل أي رابط فيديو وسأحاول تحميله وإرساله لك\n"
        "TikTok • Instagram • YouTube • Facebook • Pixeldrain ...\nجرب الآن 🚀",
        reply_markup=reply_markup,
    )


async def help_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "كيف تستخدم البوت:\n"
        "1. انسخ رابط الفيديو\n"
        "2. ألصقه هنا مباشرة\n"
        "3. انتظر قليلاً\n\n"
        "ملاحظة: المحتوى الخاص أو المقيد قد لا يعمل."
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text.startswith(("http://", "https://")):
        return
    await download_video(text, update, context)


async def owner_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    await update.message.reply_text(
        f"البوت شغال ✅\n"
        f"مالك: {OWNER_ID}\n"
        f"التاريخ: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    )


def main():
    print("دخول main()")
    if not TOKEN or ":" not in TOKEN:
        print("توكن غير صالح!")
        return

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stats", owner_stats))
    app.add_handler(CallbackQueryHandler(help_callback, pattern="^help$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("Polling بدأ...")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
