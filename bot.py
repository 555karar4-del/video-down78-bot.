import os
import asyncio
import logging
import tempfile
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv
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
import aiofiles
import ffmpeg

# ===================== CONFIG =====================
load_dotenv()

TOKEN = "8352548859:AAGxEI9yk_4TZwHO9UFZ5A7AhNU3YlvD2hQ"            # من BotFather
OWNER_ID = 6538981552  # ايديك التليجرام للتحكم
MAX_FILE_SIZE = 50 * 1024 * 1024            # حد تليجرام 50 ميجا
SUPPORTED_DOMAINS = {
    "tiktok.com", "www.tiktok.com", "vm.tiktok.com",
    "instagram.com", "www.instagram.com",
    "youtube.com", "youtu.be", "www.youtube.com",
    "facebook.com", "fb.watch", "www.facebook.com",
    "twitter.com", "x.com", "www.twitter.com",
    "threads.net",
    "pinterest.com", "pin.it",
    "likee.video", "l.likee.video",
    "kwai.com", "v.kwai.com",
    "snapchat.com",
    "soundcloud.com",
}

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# ===================== HELPER FUNCTIONS =====================

def is_supported_url(url: str) -> bool:
    domain = urlparse(url).netloc.lower()
    return any(d in domain for d in SUPPORTED_DOMAINS)


async def download_video(url: str, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    chat_id = update.effective_chat.id
    message = update.effective_message

    await message.reply_text("جاري المعالجة... يرجى الانتظار ⏳")

    ydl_opts = {
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "outtmpl": "",
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "progress_hooks": [lambda d: asyncio.create_task(progress_hook(d, context, chat_id))],
    }

    temp_dir = tempfile.mkdtemp()
    try:
        ydl_opts["outtmpl"] = os.path.join(temp_dir, "%(title)s.%(ext)s")

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = await asyncio.to_thread(ydl.extract_info, url, download=True)
            filename = ydl.prepare_filename(info)

        file_size = os.path.getsize(filename)

        if file_size > MAX_FILE_SIZE:
            await context.bot.send_message(chat_id, "الملف كبير (>50 ميجا)، جاري الضغط...")
            compressed = await compress_video(filename, temp_dir)
            if compressed:
                filename = compressed
                file_size = os.path.getsize(filename)

        caption = (
            f"🎥 {info.get('title', 'فيديو بدون عنوان')}\n"
            f"منصة: {info.get('extractor_key', 'غير معروف')}\n"
            f"تم التنزيل بواسطة @{context.bot.username}"
        )

        if file_size <= MAX_FILE_SIZE:
            await context.bot.send_video(
                chat_id=chat_id,
                video=open(filename, "rb"),
                caption=caption,
                supports_streaming=True,
                disable_notification=True,
            )
        else:
            await context.bot.send_document(
                chat_id=chat_id,
                document=open(filename, "rb"),
                caption=caption + "\n(الملف كبير - تم إرساله كملف)",
            )

    except Exception as e:
        logger.error(f"Error downloading {url}: {e}")
        await context.bot.send_message(
            chat_id=chat_id,
            text="حدث خطأ أثناء التنزيل 😔\nجرب رابط آخر أو تحقق من الإنترنت.",
        )

    finally:
        # تنظيف
        try:
            for file in Path(temp_dir).glob("*"):
                file.unlink(missing_ok=True)
            os.rmdir(temp_dir)
        except:
            pass


async def compress_video(input_path: str, temp_dir: str) -> str | None:
    output_path = os.path.join(temp_dir, "compressed_" + os.path.basename(input_path))
    try:
        stream = ffmpeg.input(input_path)
        stream = ffmpeg.output(
            stream,
            output_path,
            vcodec="libx264",
            crf=28,          # جودة جيدة + حجم صغير
            preset="fast",
            acodec="aac",
        )
        await asyncio.to_thread(ffmpeg.run, stream, overwrite_output=True, quiet=True)
        if os.path.exists(output_path) and os.path.getsize(output_path) < os.path.getsize(input_path):
            return output_path
        return None
    except Exception as e:
        logger.error(f"Compression failed: {e}")
        return None


async def progress_hook(d: dict, context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    if d["status"] == "downloading":
        percent = d.get("_percent_str", "0%")
        speed = d.get("_speed_str", "??")
        eta = d.get("_eta_str", "??")
        text = f"جاري التحميل... {percent} | ⚡ {speed} | ⏱ {eta}"
        # يمكنك إضافة edit_message_text هنا لتحديث رسالة واحدة
        # لكن للبساطة نرسل تحديث كل 5 ثوانٍ مثلاً (تجنب flood)
        # ... يمكن تحسينه باستخدام job_queue


# ===================== HANDLERS =====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("كيفية الاستخدام ℹ️", callback_data="help")],
        [InlineKeyboardButton("المبرمج 🧑‍💻", url="https://t.me/YOUR_USERNAME")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "أهلاً بك! 👋\n"
        "أنا بوت تحميل فيديوهات بدون علامة مائية من معظم المنصات:\n"
        "TikTok • Instagram • YouTube • Facebook • Twitter/X • Threads • Pinterest • Likee • Kwai ...\n\n"
        "فقط أرسل لي رابط الفيديو وسأقوم بالباقي! 🚀",
        reply_markup=reply_markup,
    )


async def help_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    text = (
        "كيف تستخدمني؟\n"
        "1. انسخ رابط أي فيديو من المنصات المدعومة\n"
        "2. أرسله هنا مباشرة\n"
        "3. انتظر قليلاً... وسيصلك الفيديو نظيف بدون علامة مائية (غالباً)\n\n"
        "مدعوم حالياً:\n" + "\n".join(f"• {d}" for d in sorted(SUPPORTED_DOMAINS))
    )
    await query.edit_message_text(text=text)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text.startswith(("http://", "https://")):
        return

    url = text
    if not is_supported_url(url):
        await update.message.reply_text(
            "الرابط غير مدعوم حالياً 😕\n"
            "جرب رابط من: TikTok, Instagram, YouTube, Facebook, Twitter/X, Threads..."
        )
        return

    await download_video(url, update, context)


async def owner_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    # يمكنك إضافة إحصائيات حقيقية من قاعدة بيانات لاحقاً
    await update.message.reply_text("إحصائيات مؤقتة: البوت شغال ✅")


def main():
    if not TOKEN:
        logger.error("BOT_TOKEN غير موجود في .env")
        return

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stats", owner_stats))
    app.add_handler(CallbackQueryHandler(help_callback, pattern="^help$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("البوت يعمل الآن...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
