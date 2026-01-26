import asyncio
import logging
import os
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, FSInputFile

import yt_dlp

# ────────────────────────────────────────────────
TOKEN = "8352548859:AAGxEI9yk_4TZwHO9UFZ5A7AhNU3YlvD2hQ"  # ← توكنك

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
        "أهلاً! أرسل رابط الفيديو من أي موقع مدعوم\n"
        "سأحمله وأضغطه إلى جودة مناسبة وأرسله لك 🎥\n\n"
        "اكتب /help للمزيد"
    )


@dp.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "كيفية الاستخدام:\n"
        "1. أرسل الرابط مباشرة\n"
        "2. البوت يحمل ويضغط تلقائيًا إلى أعلى جودة ≤480p\n"
        "3. لا رفض للفيديوهات الكبيرة – يضغط ويرسل\n"
        "4. لو كبير جدًا، يرسله كملف عادي"
    )


@dp.message()
async def handle_url(message: Message):
    text = (message.text or "").strip()

    if text.startswith('/'):
        return

    if not (text.startswith("http://") or text.startswith("https://")):
        await message.reply("أرسل رابط فيديو صالح")
        return

    processing_msg = await message.reply("جاري التحميل والضغط... ⏳ (قد يستغرق وقتًا)")

    try:
        ydl_opts = {
            'format': 'bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=480][ext=mp4]/best',
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
            f"• الجودة: ≤480p (مضغوط تلقائيًا)\n"
            f"• الحجم: {file_size_mb:.1f} ميجا"
        )

        # إرسال كفيديو لو صغير، أو كملف لو كبير
        if file_size_bytes <= 50 * 1024 * 1024:
            await bot.send_video(
                chat_id=message.chat.id,
                video=FSInputFile(file_path),
                caption=caption,
                supports_streaming=True
            )
        else:
            caption += "\n(الفيديو كبير، تم إرساله كملف – شغّله بعد التحميل)"
            await bot.send_document(
                chat_id=message.chat.id,
                document=FSInputFile(file_path),
                caption=caption
            )

        await processing_msg.delete()

        # حذف الملف بعد الإرسال
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
    await dp.start_polling(bot, drop_pending_updates=True)


if __name__ == "__main__":
    asyncio.run(main())
