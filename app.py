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

TOKEN = "8352548859:AAGxEI9yk_4TZwHO9UFZ5A7AhNU3YlvD2hQ"
OWNER_ID = 6538981552
MAX_FILE_SIZE = 50 * 1024 * 1024

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
        'extractor_args': {'youtube': {'player_client': ['web', 'ios', 'android', 'web_embedded']}},
        'impersonate': 'chrome',  # أفضل قيمة حالياً (بدون رقم إصدار عشان يختار أحدث تلقائي)
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

            # Pixeldrain مباشر
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
                        print(f"Pixeldrain مباشر → {filename}")
                except Exception as pix_err:
                    logger.warning(f"Pixeldrain فشل: {pix_err}")

            # yt-dlp الرئيسي
            if not filename:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info_dict = await asyncio.to_thread(ydl.extract_info, url, download=True)
                    filename = ydl.prepare_filename(info_dict)

            if not filename or not os.path.exists(filename):
                raise Exception("لم يتم تنزيل الملف")

            # تحويل إلى mp4 إذا لزم
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
                    pass

            file_size = os.path.getsize(filename)

            if file_size > MAX_FILE_SIZE:
                await progress.edit_text("الملف كبير (>50MB) → جاري الضغط...")
                compressed = await compress_video(filename, temp_dir)
                if compressed:
                    filename = compressed
                    file_size = os.path.getsize(filename)

            # اسم الموقع للـ caption
            extractor = info_dict.get('extractor_key', 'مباشر') if info_dict else 'Pixeldrain'
            site_name = extractor
            title = info_dict.get('title', 'فيديو بدون عنوان') if info_dict else Path(filename).stem
            caption = f"🎬 {title[:180]}\n• من: {site_name}\n• بواسطة @{context.bot.username}"

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
            logger.error(f"ERROR في {url}: {str(e)}", exc_info=True)  # ← مهم للـ logs في Railway

            if "sign in to confirm" in error_str or "you're not a bot" in error_str or "bot" in error_str:
                text = "يوتيوب يكتشف الطلب كـ 'بوت' (شائع على السيرفرات مثل Railway).\nجرب روابط من TikTok، Instagram، Pixeldrain، Facebook... غالباً يشتغلون بدون مشكلة."
            elif "private" in error_str or "restricted" in error_str or "login" in error_str or "age" in error_str:
                text = "المحتوى خاص أو مقيد أو يحتاج تسجيل دخول."
            elif "geo" in error_str or "unavailable" in error_str or "blocked" in error_str:
                text = "المحتوى مقيد جغرافياً أو غير متوفر."
            elif "no video" in error_str or "no formats" in error_str or "cannot parse" in error_str:
                text = "ما قدرنا نستخرج الفيديو (ربما الرابط تالف أو مشكلة مؤقتة)."
            else:
                text = f"خطأ غير متوقع: {str(e)[:120]}...\nجرب رابط آخر أو أرسل الرابط لي أشوفه."

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
        "مرحباً كرار! 👋\n"
        "أرسل أي رابط فيديو وسأحاول تحميله وإرساله لك\n"
        "يدعم معظم المواقع: TikTok • Instagram • Facebook • X/Twitter • Pixeldrain • Vimeo • SoundCloud ...\n"
        "ملاحظة: بعض فيديوهات YouTube قد تكون صعبة بسبب قيود جوجل (جرب روابط أخرى أولاً).\n"
        "جرب الآن 🚀",
        reply_markup=reply_markup,
    )


async def help_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "كيف تستخدم البوت:\n"
        "1. انسخ رابط الفيديو (من أي موقع)\n"
        "2. ألصقه هنا مباشرة\n"
        "3. انتظر النتيجة\n\n"
        "يدعم آلاف المواقع عبر yt-dlp.\n"
        "المحتوى الخاص أو المقيد قد لا يعمل دائماً."
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
        f"البوت شغال ✅\nمالك: {OWNER_ID}\nالتاريخ: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
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
