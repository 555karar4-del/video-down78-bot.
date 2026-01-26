import asyncio
import logging
import os
from pathlib import Path
import requests

from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

import yt_dlp

TOKEN = "8352548859:AAGxEI9yk_4TZwHO9UFZ5A7AhNU3YlvD2hQ"  # توكنك الحالي

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN)
dp = Dispatcher()

DOWNLOAD_DIR = Path("downloads")
DOWNLOAD_DIR.mkdir(exist_ok=True)

# ────────────────────────────────────────────────
@dp.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(
        "أهلاً! أرسل رابط الفيديو من أي موقع (يوتيوب، تيك توك، إنستغرام، X، فيسبوك...)\n"
        "سأعرض لك الجودات المتاحة للتحميل 🎥"
    )


@dp.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer("فقط أرسل الرابط وسأعطيك خيارات الجودة والصوت")


@dp.message()
async def handle_link(message: Message):
    url = message.text.strip()
    if not url.startswith(('http://', 'https://')):
        await message.reply("أرسل رابط صالح يبدأ بـ http أو https")
        return

    processing = await message.reply("جاري استخراج الجودات... ⏳")

    try:
        ydl_opts = {
            'quiet': True,
            'simulate': True,
            'listformats': True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        formats = info.get('formats', [])
        qualities = []

        for f in formats:
            if f.get('vcodec') != 'none' and f.get('ext') == 'mp4':
                height = f.get('height')
                if height and height >= 240:
                    size_mb = f.get('filesize') / (1024 * 1024) if f.get('filesize') else "غير معروف"
                    qualities.append((height, f['format_id'], size_mb))

        qualities = sorted(set(qualities), reverse=True)[:6]  # أعلى 6 جودات

        keyboard = []
        for height, fmt_id, size in qualities:
            btn_text = f"{height}p (~{size} MB)" if isinstance(size, (int, float)) else f"{height}p"
            keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"vid|{fmt_id}|{url}")])

        keyboard.append([InlineKeyboardButton("صوت فقط (mp3)", callback_data=f"aud|{url}")])

        reply_markup = InlineKeyboardMarkup(inline_keyboard=keyboard)

        thumbnail = info.get('thumbnail') or (info.get('thumbnails', [{}])[0].get('url') if info.get('thumbnails') else None)
        caption = f"العنوان: {info.get('title', 'بدون عنوان')}\nالمدة: {info.get('duration_string', 'غير معروف')}\nاختر الجودة:"

        if thumbnail:
            await bot.send_photo(
                chat_id=message.chat.id,
                photo=thumbnail,
                caption=caption,
                reply_markup=reply_markup
            )
        else:
            await message.reply(caption, reply_markup=reply_markup)

        await processing.delete()

    except Exception as e:
        await processing.edit_text(f"خطأ في استخراج الجودات:\n{str(e)[:300]}\nجرب رابط آخر")


@dp.callback_query()
async def callback_handler(query: CallbackQuery):
    await query.answer()
    data = query.data
    if data.startswith("vid|"):
        _, format_id, url = data.split("|", 2)
        processing = await query.message.edit_text("جاري التحميل بهذه الجودة... ⏳")
        try:
            ydl_opts = {
                'format': format_id,
                'outtmpl': str(DOWNLOAD_DIR / '%(title)s.%(ext)s'),
                'quiet': True,
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info)
            file_path = Path(filename)
            file_size_mb = file_path.stat().st_size / (1024 * 1024)

            if file_size_mb <= 50:
                await bot.send_video(
                    chat_id=query.message.chat.id,
                    video=FSInputFile(file_path),
                    caption=f"تم التحميل بجودة {format_id} ({file_size_mb:.1f} ميجا)",
                    supports_streaming=True
                )
            else:
                # رفع خارجي على tmpfiles.org
                files = {'file': open(file_path, 'rb')}
                r = requests.post('https://tmpfiles.org/api/v1/upload', files=files, timeout=120)
                if r.status_code == 200:
                    link = r.json()['data']['url']['direct_link']
                    await query.message.edit_text(
                        f"الفيديو كبير ({file_size_mb:.1f} ميجا)\n"
                        f"حمل من هنا (24 ساعة):\n{link}"
                    )
                else:
                    await query.message.edit_text("فشل الرفع الخارجي، جرب جودة أقل")
            file_path.unlink()
        except Exception as e:
            await processing.edit_text(f"فشل التحميل: {str(e)[:200]}")
        await processing.delete()

    elif data.startswith("aud|"):
        _, url = data.split("|", 1)
        processing = await query.message.edit_text("جاري استخراج الصوت (mp3)... ⏳")
        try:
            ydl_opts = {
                'format': 'bestaudio/best',
                'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3'}],
                'outtmpl': str(DOWNLOAD_DIR / '%(title)s.%(ext)s'),
                'quiet': True,
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info).rsplit('.', 1)[0] + '.mp3'
            file_path = Path(filename)
            await bot.send_audio(
                chat_id=query.message.chat.id,
                audio=FSInputFile(file_path),
                title=info.get('title', 'صوت')
            )
            file_path.unlink()
        except Exception as e:
            await processing.edit_text(f"فشل استخراج الصوت: {str(e)[:200]}")
        await processing.delete()

async def main():
    logging.info("البوت بدأ العمل...")
    await dp.start_polling(bot, drop_pending_updates=True)


if __name__ == "__main__":
    asyncio.run(main())
