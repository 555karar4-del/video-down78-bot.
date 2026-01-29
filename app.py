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

TOKEN = "7059711469:AAHZklgdoyO-lwcdLLHoL0yWt_gt8cwEn1U"  # ← التوكن الجديد
OWNER_ID = 6538981552
MAX_FILE_SIZE = 50 * 1024 * 1024

print("الإعدادات تم تحميلها")


# ────────────────────────────────────────
# Error Handler جديد (مهم جداً لـ Railway)
# ────────────────────────────────────────
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """يُسجل الأخطاء ويمنع توقف البوت عند حدوث exception"""
    logger.error(f"Exception while handling update: {context.error}", exc_info=True)
    
    # اختياري: إرسال تنبيه للمالك
    if OWNER_ID:
        try:
            await context.bot.send_message(
                chat_id=OWNER_ID,
                text=f"⚠️ خطأ في البوت:\n{context.error}\n\nرابط الطلب: {update.effective_message.text if update and update.effective_message else 'غير معروف'}"
            )
        except:
            pass


async def download_video(url: str, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    message = update.effective_message

    progress = await message.reply_text("جاري المعالجة... ⏳")

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
        'extractor_args': {'youtube': {'player_client': ['web', 'ios', 'android', 'web_embedded']}},
        'impersonate': 'chrome',
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
            'Referer': 'https://www.google.com/',
        },
        'force_generic_extractor': False,
    }

    with tempfile.TemporaryDirectory() as temp_dir:
        filename = None
        info_dict = None

        try:
            ydl_opts['outtmpl'] = os.path.join(temp_dir, '%(title).180s.%(ext)s')

            # Pixeldrain مباشر - أولوية عالية
            if "pixeldrain.com" in url.lower():
                file_id = url.split("/")[-1].split("?")[0].split("#")[0]
                direct_url = f"https://cdn.pixeldrain.com/u/{file_id}"
                try:
                    headers = ydl_opts['http_headers'].copy()
                    headers['Referer'] = 'https://pixeldrain.com/'

                    session = requests.Session()
                    r = session.get(direct_url, stream=True, timeout=180, headers=headers, allow_redirects=True)

                    if r.status_code == 200:
                        content_type = r.headers.get("Content-Type", "").lower()
                        ext = ".mp4"
                        if "audio" in content_type:
                            ext = ".m4a" if "mp4" not in content_type else ".mp4"
                        elif "matroska" in content_type:
                            ext = ".mkv"

                        filename = os.path.join(temp_dir, f"pixeldrain_{file_id}{ext}")

                        downloaded = 0
                        with open(filename, "wb") as f:
                            for chunk in r.iter_content(chunk_size=16384):
                                if chunk:
                                    f.write(chunk)
                                    downloaded += len(chunk)
                                    if downloaded % (5 * 1024 * 1024) == 0:
                                        mb = downloaded // (1024 * 1024)
                                        await progress.edit_text(f"جاري تنزيل Pixeldrain... ({mb} MB)")

                        file_size_check = os.path.getsize(filename)
                        if file_size_check > 500_000:
                            logger.info(f"نجاح Pixeldrain مباشر: {filename} ({file_size_check / (1024*1024):.1f} MB)")
                        else:
                            raise Exception(f"ملف صغير جداً ({file_size_check} بايت)")
                    else:
                        raise Exception(f"Pixeldrain حالة {r.status_code} - {r.reason}")

                except Exception as pix_err:
                    logger.error(f"Pixeldrain فشل: {str(pix_err)}", exc_info=True)
                    await progress.edit_text("فشل المباشر → جاري yt-dlp...")

            # yt-dlp إذا لم ينجح المباشر
            if filename is None:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info_dict = await asyncio.to_thread(ydl.extract_info, url, download=True)
                    filename = ydl.prepare_filename(info_dict)

            if filename is None or not os.path.exists(filename):
                raise Exception("لم يتم تنزيل الملف")

            # تحويل إلى mp4 إذا لزم
            if not filename.lower().endswith(('.mp4', '.m4v')):
                new_filename = filename.rsplit('.', 1)[0] + '.mp4'
                try:
                    stream = ffmpeg.input(filename)
                    stream = ffmpeg.output(stream, new_filename, c='copy', movflags='faststart')
                    await asyncio.to_thread(ffmpeg.run, stream, overwrite_output=True, quiet=True)
                    if os.path.exists(new_filename) and os.path.getsize(new_filename) > 100000:
                        os.remove(filename)
                        filename = new_filename
                except Exception as conv_err:
                    logger.warning(f"تحويل mp4 فشل: {conv_err}")

            file_size = os.path.getsize(filename)

            if file_size > MAX_FILE_SIZE:
                await progress.edit_text("الملف كبير (>50MB) → جاري الضغط...")
                compressed = await compress_video(filename, temp_dir)
                if compressed:
                    filename = compressed
                    file_size = os.path.getsize(filename)

            extractor = info_dict.get('extractor_key', 'Pixeldrain مباشر') if info_dict else 'Pixeldrain'
            title = info_dict.get('title', Path(filename).stem) if info_dict else Path(filename).stem
            caption = f"🎬 {title[:180]}\n• من: {extractor}\n• حجم: {file_size // (1024*1024)} MB\n• بواسطة @{context.bot.username}"

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
            error_str = str(e).lower()
            logger.error(f"خطأ في {url}: {str(e)}", exc_info=True)

            if "sign in to confirm" in error_str or "you're not a bot" in error_str:
                text = "يوتيوب يكتشف 'بوت' (شائع على السيرفرات).\nجرب TikTok/Instagram/Pixeldrain."
            elif "private" in error_str or "restricted" in error_str or "login" in error_str or "age" in error_str:
                text = "محتوى خاص أو مقيد أو يحتاج تسجيل."
            elif "geo" in error_str or "unavailable" in error_str or "blocked" in error_str:
                text = "مقيد جغرافياً أو غير متوفر."
            elif "no video" in error_str or "formats" in error_str or "cannot parse" in error_str:
                text = "تعذر استخراج الفيديو."
            elif "pixeldrain" in error_str:
                text = "مشكلة Pixeldrain (timeout أو رد غير متوقع)."
            else:
                text = f"خطأ: {str(e)[:140]}...\nجرب رابط آخر."

            await progress.edit_text(text)


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
            if size > 300_000:
                return output_path
        return None
    except Exception as e:
        logger.error(f"فشل الضغط: {e}")
        return None


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("كيفية الاستخدام ℹ️", callback_data="help")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "مرحباً! 👋\n"
        "أرسل أي رابط فيديو وسأحاول تحميله\n"
        "يدعم: TikTok • Instagram • Facebook • X • Pixeldrain • Vimeo ...\n"
        "جرب الآن 🚀",
        reply_markup=reply_markup,
    )


async def help_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "1. انسخ الرابط\n2. ألصقه هنا\n3. انتظر النتيجة\n\n"
        "المحتوى الخاص قد لا يعمل دائماً."
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
        f"شغال ✅ | مالك: {OWNER_ID} | {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    )


def main():
    print("دخول main()")
    if not TOKEN or ":" not in TOKEN:
        print("توكن غير صالح!")
        return

    app = Application.builder().token(TOKEN).build()

    # إضافة error handler
    app.add_error_handler(error_handler)

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stats", owner_stats))
    app.add_handler(CallbackQueryHandler(help_callback, pattern="^help$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("Polling بدأ")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
