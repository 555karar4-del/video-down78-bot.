import asyncio
import logging
import os
from pathlib import Path
import subprocess

from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, FSInputFile

import yt_dlp

# ────────────────────────────────────────────────
TOKEN = "8352548859:AAGxEI9yk_4TZwHO9UFZ5A7AhNU3YlvD2hQ"  # ← غيّر هذا بالتوكن الحقيقي الخاص بك

if not TOKEN:
    raise ValueError("البوت بدون توكن!")

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN)
dp = Dispatcher()

DOWNLOAD_DIR = Path("downloads")
DOWNLOAD_DIR.mkdir(exist_ok=True)

MAX_VIDEO_SIZE = 48 * 1024 * 1024  # 48 ميجا لكل جزء (احتياطي تحت 50)

# ────────────────────────────────────────────────
@dp.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(
        "أهلاً! أرسل أي رابط فيديو أو صورة أو صوت (تيك توك، يوتيوب، فيسبوك، إنستغرام، X، إلخ)\n"
        "سأحمل أفضل جودة متاحة وأرسلها لك مباشرة 🎥\n\n"
        "اكتب /help إذا احتجت مساعدة"
    )


@dp.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "كيف تستخدم البوت:\n"
        "1. أرسل الرابط مباشرة\n"
        "2. يحمل أفضل جودة تلقائيًا (فيديو + صوت)\n"
        "3. الحد الأقصى للإرسال المباشر ~50 ميجا\n"
        "4. لو الفيديو كبير جدًا، يقسمه إلى أجزاء ويرسلها منفصلة\n\n"
        "يدعم تقريبًا كل المواقع"
    )


@dp.message()
async def handle_link(message: Message):
    text = (message.text or "").strip()

    if not (text.startswith("http://") or text.startswith("https://")):
        return  # تجاهل الرسائل غير الروابط

    processing_msg = await message.reply("جاري التحميل... انتظر قليلاً ⏳ (10–60 ثانية)")

    try:
        ydl_opts = {
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            'outtmpl': str(DOWNLOAD_DIR / '%(title)s.%(ext)s'),
            'quiet': False,
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
            f"• {info.get('title', 'بدون عنوان')}\n"
            f"• المصدر: {info.get('webpage_url', text)[:100]}\n"
            f"• الحجم الأصلي: {file_size_mb:.1f} ميجا"
        )

        if file_size_bytes <= 50 * 1024 * 1024:
            await bot.send_video(
                chat_id=message.chat.id,
                video=FSInputFile(file_path),
                caption=caption,
                supports_streaming=True
            )
            await processing_msg.delete()
        else:
            # تقسيم الفيديو
            num_parts = (file_size_bytes // MAX_VIDEO_SIZE) + 1
            duration = info.get('duration', 0)
            segment_duration = duration / num_parts if duration else 300  # تقديري 5 دقائق

            parts = []
            for i in range(num_parts):
                part_path = file_path.with_name(f"{file_path.stem}_part{i+1}{file_path.suffix}")
                start_time = i * segment_duration
                subprocess.run([
                    'ffmpeg', '-i', str(file_path),
                    '-ss', str(start_time), '-t', str(segment_duration),
                    '-c', 'copy', str(part_path)
                ], check=True)
                parts.append(part_path)

            # إرسال الأجزاء
            for idx, part_path in enumerate(parts, 1):
                part_size_mb = part_path.stat().st_size / (1024 * 1024)
                caption_part = f"{caption}\nالجزء {idx}/{len(parts)} ({part_size_mb:.1f} ميجا)"
                await bot.send_video(
                    chat_id=message.chat.id,
                    video=FSInputFile(part_path),
                    caption=caption_part,
                    supports_streaming=True
                )
                try:
                    part_path.unlink()
                except:
                    pass

            await processing_msg.edit_text(
                "تم إرسال الفيديو كاملاً على مراحل (الجودة عالية جدًا)\n"
                "شغّل الأجزاء بالترتيب"
            )

        # حذف الفيديو الأصلي
        try:
            if file_path.exists():
                file_path.unlink()
        except:
            pass

    except yt_dlp.utils.DownloadError as e:
        await processing_msg.edit_text(f"خطأ في التحميل:\n{str(e)[:400]}\nجرب رابط آخر")
    except Exception as e:
        logging.exception("خطأ غير متوقع")
        await processing_msg.edit_text(f"حصل خطأ:\n{str(e)[:300]}\nأعد المحاولة")

async def main():
    logging.info("البوت بدأ العمل...")
    await dp.start_polling(bot, drop_pending_updates=True)


if __name__ == "__main__":
    asyncio.run(main())
