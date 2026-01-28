import os
import asyncio
import logging
import tempfile
import subprocess
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

# ────────────────────────────────────────────────
#                 Logging + ffmpeg check
# ────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

print("بدء التنفيذ: Imports جارية...")

# تحديث yt-dlp ذاتياً (مهم لفيسبوك)
try:
    subprocess.run(["yt-dlp", "-U"], check=True, capture_output=True)
    print("yt-dlp تم تحديثه إلى أحدث إصدار")
except Exception as e:
    print(f"فشل تحديث yt-dlp: {e} – سيستمر بالإصدار الحالي")

# تحقق ffmpeg
print("جاري التحقق من ffmpeg...")
try:
    result = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True, timeout=5)
    if result.returncode == 0:
        print("ffmpeg موجود ✓ الإصدار: " + result.stdout.splitlines()[0])
    else:
        print("ffmpeg خطأ: " + result.stderr.strip())
except FileNotFoundError:
    print("ffmpeg غير موجود! (FileNotFoundError)")
except Exception as e:
    print(f"خطأ في التحقق من ffmpeg: {e}")

# ────────────────────────────────────────────────
#                 الإعدادات الرئيسية
# ────────────────────────────────────────────────

TOKEN = "8352548859:AAGxEI9yk_4TZwHO9UFZ5A7AhNU3YlvD2hQ"
OWNER_ID = 6538981552

MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 ميجا

SUPPORTED_DOMAINS = {
    "tiktok.com", "www.tiktok.com", "vm.tiktok.com", "vt.tiktok.com",
    "instagram.com", "www.instagram.com",
    "youtube.com", "youtu.be", "www.youtube.com",
    "facebook.com", "fb.watch", "www.facebook.com",
    "twitter.com", "x.com", "www.twitter.com", "www.x.com",
    "threads.net",
    "pinterest.com", "pin.it",
    "likee.video", "l.likee.video",
    "kwai.com", "v.kwai.com",
    "snapchat.com",
    "soundcloud.com",
}

print("الإعدادات تم تحميلها")

# ────────────────────────────────────────────────
#                الدوال المساعدة
# ────────────────────────────────────────────────

def is_supported_url(url: str) -> bool:
    domain = urlparse(url).netloc.lower().replace("www.", "")
    return any(d in domain for d in SUPPORTED_DOMAINS)


async def download_video(url: str, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    message = update.effective_message

    progress_msg = await message.reply_text("جاري المعالجة... ⏳ (قد يستغرق دقيقة)")

    ydl_opts = {
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/bestvideo+bestaudio/best',
        'outtmpl': '',
        'quiet': True,
        'no_warnings': True,
        'noplaylist': True,
        'impersonate': 'chrome124',  # يحاكي متصفح حديث – يساعد كثيراً مع فيسبوك 2026
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0',
            'Referer': 'https://www.facebook.com/',
            'Accept-Language': 'en-US,en;q=0.9',
        },
        'extractor_args': {'facebook': {'approximate_date': 'now'}},
        'retries': 10,
        'fragment_retries': 10,
    }

    temp_dir = tempfile.mkdtemp()
    try:
        ydl_opts['outtmpl'] = os.path.join(temp_dir, "%(title)s.%(ext)s")

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = await asyncio.to_thread(ydl.extract_info, url, download=True)
            filename = ydl.prepare_filename(info)

        file_size = os.path.getsize(filename)

        if file_size > MAX_FILE_SIZE:
            await progress_msg.edit_text("الملف كبير (>50 ميجا) → جاري الضغط...")
            compressed = await compress_video(filename, temp_dir)
            if compressed:
                filename = compressed
                file_size = os.path.getsize(filename)

        caption = (
            f"🎬 {info.get('title', 'فيديو بدون عنوان')}\n"
            f"• منصة: {info.get('extractor_key', 'غير معروف')}\n"
            f"• تم التحميل بواسطة @{context.bot.username}"
        )

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
        if "private" in error_str or "login" in error_str or "restricted" in error_str:
            await progress_msg.edit_text("الفيديو خاص أو مقيد (يتطلب تسجيل دخول). لا يمكن تحميله بدون cookies من حسابك.")
        elif "no video formats" in error_str or "cannot parse" in error_str:
            await progress_msg.edit_text("فشل استخراج الفيديو (غالباً فيسبوك غير مدعوم مؤقتاً). جرب تحديث yt-dlp أو رابط آخر.")
        elif "geo" in error_str or "blocked" in error_str:
            await progress_msg.edit_text("الفيديو مقيد جغرافياً أو محظور في منطقتك.")
        else:
            await progress_msg.edit_text(f"خطأ: {str(e)[:150]}...\nجرب رابط آخر أو انتظر قليلاً.")
        logger.error(f"خطأ تنزيل {url}: {str(e)}", exc_info=True)

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
        logger.error(f"فشل ضغط: {e}")
        return None


# ────────────────────────────────────────────────
#                   الهاندلرز
# ────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("كيفية الاستخدام ℹ️", callback_data="help")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "مرحباً كرار! 👋\n"
        "أرسل رابط فيديو من أي منصة مدعومة وسأحاول تحميله بدون علامة مائية\n\n"
        "المدعوم: تيك توك • إنستغرام • يوتيوب • فيسبوك (عام) • تويتر/X • ثريدز • بينترست • لايكي • كواي ...\n\n"
        "جرب الآن! 🚀",
        reply_markup=reply_markup,
    )


async def help_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    text = (
        "1. انسخ رابط الفيديو\n"
        "2. ألصقه هنا\n"
        "3. انتظر → الفيديو ينزل نظيف (إذا عام)\n\n"
        "ملاحظة: الفيديوهات الخاصة في فيسبوك تحتاج cookies (غير مدعوم حالياً)\n"
        "المنصات:\n" + " • " + "\n • ".join(sorted(SUPPORTED_DOMAINS))
    )
    await query.edit_message_text(text)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text.startswith(("http://", "https://")):
        return

    url = text
    if not is_supported_url(url):
        await update.message.reply_text("الرابط غير مدعوم 😕")
        return

    await download_video(url, update, context)


async def owner_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    await update.message.reply_text(
        f"إحصائيات:\n"
        f"• شغال ✅\n"
        f"• مالك ID: {OWNER_ID}\n"
        f"• وقت: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    )


def main():
    print("دخول main() ...")
    if not TOKEN or ":" not in TOKEN:
        print("توكن خاطئ!")
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
