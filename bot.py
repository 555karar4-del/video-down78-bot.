import asyncio
import logging
import os
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, FSInputFile

import yt_dlp

# ────────────────────────────────────────────────
TOKEN = "8352548859:AAGxEI9yk_4TZwHO9UFZ5A7AhNU3YlvD2hQ"  # ← توكنك الحقيقي هنا

if not TOKEN:
    raise ValueError("BOT_TOKEN غير موجود!")

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN)
dp = Dispatcher()

DOWNLOAD_DIR = Path("downloads")
DOWNLOAD_DIR.mkdir(exist_ok=True)

# ────────────────────────────────────────────────
@dp.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(
        "أهلاً! أرسل رابط الفيديو من أي موقع مدعوم (يوتيوب، تيك توك، إنستغرام، X، فيسبوك...)\n"
        "سأحاول تحميله بأعلى جودة ممكنة وإرساله لك 🎥\n\n"
        "اكتب /help للمزيد"
    )


@dp.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "كيفية الاستخدام:\n"
        "1. أرسل الرابط مباشرة\n"
        "2. يدعم معظم المواقع عبر yt-dlp\n"
        "3. الحد الأقصى ~50 ميجا للإرسال المباشر\n"
        "4. إذا كان كبير → سيخبرك البوت\n\n"
        "مشاكل؟ جرب رابط آخر."
    )


@dp.message()
async def handle_url(message: Message):
    text = (message.text or "").strip()

    if text.startswith('/'):
        return  # تجاهل الأوامر

    if not (text.startswith("http://") or text.startswith("https://")):
        await message.reply("أرسل رابط فيديو صالح (http أو https)")
        return

    processing_msg = await message.reply("جاري التحميل... ⏳ (10–60 ثانية)")

    try:
        ydl_opts = {
            'format': 'bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080][ext=mp4]/best',
            'outtmpl': str(DOWNLOAD_DIR / '%(title)s.%(ext)s'),
            'quiet': True,
            'no_warnings': True,
            'continuedl': True,
            'retries': 10,
            'noplaylist': True,
            'geo_bypass': True,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(text, download=True)
            filename = ydl.prepare_filename(info)

        file_path = Path(filename)
        file_size_bytes = file_path.stat().st_size
        file_size_mb = file_size_bytes / (1024 * 1024)

        caption = (
            f"• {info.get('title', 'فيديو')}\n"
            f"• من: {info.get('webpage_url', text)[:100]}\n"
            f"• الجودة: {info.get('resolution', 'غير معروف')}\n"
            f"• الحجم: {file_size_mb:.1f} ميجا"
        )

        if file_size_bytes > 50 * 1024 * 1024:
            await processing_msg.edit_text(
                f"الفيديو كبير جدًا ({file_size_mb:.1f} ميجا)\n"
                "حد تيليجرام ~50 ميجا للفيديو المباشر 😔\n"
                "جرب جودة أقل"
            )
        else:
            await bot.send_video(
                chat_id=message.chat.id,
                video=FSInputFile(file_path),
                caption=caption,
                supports_streaming=True
            )
            await processing_msg.delete()

        try:
            if file_path.exists():
                file_path.unlink()
        except Exception as e:
            logging.warning(f"فشل حذف {file_path}: {e}")

    except yt_dlp.utils.DownloadError as e:
        await processing_msg.edit_text(f"خطأ في التحميل:\n{str(e)[:300]}\nجرب رابط آخر")
    except Exception as e:
        logging.exception("خطأ غير متوقع")
        await processing_msg.edit_text(f"حصل خطأ غير متوقع:\n{str(e)[:200]}\nأعد المحاولة")

async def main():
    logging.info("البوت يبدأ العمل...")
    await dp.start_polling(
        bot,
        drop_pending_updates=True
    )


if __name__ == "__main__":
    asyncio.run(main())
