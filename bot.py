import os
import asyncio
import logging
import tempfile
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

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ────────────────────────────────────────────────
#                الدوال المساعدة
# ────────────────────────────────────────────────

def is_supported_url(url: str) -> bool:
    domain = urlparse(url).netloc.lower().replace("www.", "")
    return any(d in domain for d in SUPPORTED_DOMAINS)


async def download_video(url: str, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    message = update.effective_message

    progress_msg = await message.reply_text("جاري استخراج الفيديو... ⏳")

    ydl_opts = {
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "outtmpl": "",
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
    }

    temp_dir = tempfile.mkdtemp()
    try:
        ydl_opts["outtmpl"] = os.path.join(temp_dir, "%(title)s.%(ext)s")

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = await asyncio.to_thread(ydl.extract_info, url, download=True)
            filename = ydl.prepare_filename(info)

        file_size = os.path.getsize(filename)

        # ضغط إذا تجاوز الحد
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
                caption=caption + "\n(تم إرساله كملف لأن الحجم كبير)",
                reply_to_message_id=message.message_id,
            )

        await progress_msg.delete()

    except Exception as e:
        logger.error(f"خطأ في {url}: {str(e)}", exc_info=True)
        await progress_msg.edit_text(
            "حدث خطأ أثناء التحميل 😔\nجرب رابط آخر أو تحقق من اتصالك."
        )

    finally:
        try:
            for file in Path(temp_dir).glob("*"):
                file.unlink(missing_ok=True)
            os.rmdir(temp_dir)
        except:
            pass


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


# ────────────────────────────────────────────────
#                   الهاندلرز
# ────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("كيفية الاستخدام ℹ️", callback_data="help")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "مرحباً! 👋\n"
        "أرسل لي رابط فيديو من أي منصة مدعومة وسأحمل لك الفيديو بدون علامة مائية (غالباً)\n\n"
        "المنصات المدعومة حالياً:\n"
        "• تيك توك • إنستغرام • يوتيوب • فيسبوك • تويتر/X • ثريدز • بينترست • لايكي • كواي ...\n\n"
        "جرب الآن 🚀",
        reply_markup=reply_markup,
    )


async def help_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    text = (
        "طريقة الاستخدام بسيطة:\n"
        "1. انسخ رابط الفيديو\n"
        "2. ألصقه هنا مباشرة\n"
        "3. انتظر ثواني وسيصلك الفيديو نظيف\n\n"
        "مدعوم حالياً:\n" + " • " + "\n • ".join(sorted(d for d in SUPPORTED_DOMAINS))
    )
    await query.edit_message_text(text)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text.startswith(("http://", "https://")):
        return

    url = text
    if not is_supported_url(url):
        await update.message.reply_text("هذا الرابط غير مدعوم حالياً 😕")
        return

    await download_video(url, update, context)


async def owner_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    await update.message.reply_text(
        f"إحصائيات سريعة:\n"
        f"• البوت شغال ✅\n"
        f"• معرف المالك: {OWNER_ID}\n"
        f"• الوقت الحالي: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    )


def main():
    if not TOKEN or len(TOKEN.split(":")) != 2:
        print("التوكن غير صحيح! تحقق منه.")
        return

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stats", owner_stats))
    app.add_handler(CallbackQueryHandler(help_callback, pattern="^help$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("البوت يبدأ التشغيل الآن...")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
