import asyncio
import logging
import os
from pathlib import Path
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, FSInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
import yt_dlp
from dotenv import load_dotenv

# ────────────────────────────────────────────────
load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")          # أو اكتب التوكن مباشرة هنا (غير مستحسن)
TOKEN = "8352548859:AAGxEI9yk_4TZwHO9UFZ5A7AhNU3YlvD2hQ"  # توكنك الحقيقي هنا

if not TOKEN:
    raise ValueError("BOT_TOKEN غير موجود في .env أو في الكود!")

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

DOWNLOAD_DIR = Path("downloads")
DOWNLOAD_DIR.mkdir(exist_ok=True)

class DownloadStates(StatesGroup):
    waiting_url = State()

# ────────────────────────────────────────────────
@dp.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(
        "أهلاً! أرسل رابط الفيديو من أي موقع مدعوم (يوتيوب، تيك توك، إنستغرام، X، فيسبوك...)\n"
        "سأحاول تحميله بأعلى جودة ممكنة وإرساله لك 🎥\n\n"
        "أو اكتب /help للمزيد من التعليمات"
    )

@dp.message(Command("help"))
async def cmd_help(message: Message):
    text = (
        "كيفية الاستخدام:\n"
        "1. فقط أرسل الرابط مباشرة (لا تحتاج أمر)\n"
        "2. البوت يدعم معظم المواقع التي يدعمها yt-dlp\n"
        "3. الحد الأقصى ~50 ميجا (حد تيليجرام للبوتات العادية)\n"
        "4. إذا كان الفيديو كبير → سيخبرك البوت\n\n"
        "مشاكل شائعة؟ أعد تشغيل البوت أو جرب رابط آخر."
    )
    await message.answer(text)

# ────────────────────────────────────────────────
@dp.message()
async def handle_any_message(message: Message, state: FSMContext):
    text = message.text.strip()

    if not (text.startswith("http://") or text.startswith("https://")):
        await message.reply("أرسل رابط فيديو صالح يبدأ بـ http/https")
        return

    processing_msg = await message.reply("جاري استخراج وتحميل الفيديو... ⏳ (قد يأخذ 10–60 ثانية)")

    try:
        ydl_opts = {
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            'outtmpl': str(DOWNLOAD_DIR / '%(title)s.%(ext)s'),
            'quiet': True,
            'no_warnings': True,
            'continuedl': True,
            'retries': 10,
            'noplaylist': True,           # تجنب تحميل قوائم التشغيل تلقائياً
            'geo_bypass': True,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(text, download=True)
            filename = ydl.prepare_filename(info)

        file_path = Path(filename)
        file_size_mb = file_path.stat().st_size / (1024 * 1024)

        if file_size_mb > 48:  # احتياطي تحت 50 ميجا
            await processing_msg.edit_text(
                f"الفيديو كبير جداً ({file_size_mb:.1f} ميجا)\n"
                "تيليجرام لا يسمح بإرسال ملفات أكبر من ~50 ميجا مباشرة 😔"
            )
        else:
            await bot.send_video(
                chat_id=message.chat.id,
                video=FSInputFile(file_path),
                caption=f"• {info.get('title', 'فيديو بدون عنوان')}\n"
                        f"• من: {info.get('webpage_url', text)[:100]}\n"
                        f"• الجودة: {info.get('resolution', 'غير معروف')}",
                supports_streaming=True
            )
            await processing_msg.delete()

        # تنظيف الملف بعد الإرسال
        if file_path.exists():
            file_path.unlink()

    except yt_dlp.utils.DownloadError as e:
        await processing_msg.edit_text(f"خطأ في التحميل:\n{str(e)[:300]}\nجرب رابط آخر أو انتظر قليلاً")
    except Exception as e:
        logging.exception("Unexpected error")
        await processing_msg.edit_text(f"حصل خطأ غير متوقع:\n{str(e)[:200]}\nأعد المحاولة لاحقاً")

# ────────────────────────────────────────────────
async def main():
    logging.info("البوت يبدأ العمل...")
    await dp.start_polling(bot, allowed_updates=types.Update.ALL_TYPES)

if __name__ == "__main__":
    asyncio.run(main())
