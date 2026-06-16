import asyncio
import logging
import os
import random
import re
import tempfile

import yt_dlp
from telegram import Update
from telegram.ext import ContextTypes

_SUPPORTED_RE = re.compile(r"https?://(?:www\.)?instagram\.com/\S+")

logger = logging.getLogger(__name__)

_MAX_BYTES = 80 * 1024 * 1024  # 80 MB upload limit
_TMPDIR = os.path.join(os.path.dirname(__file__), "downloads")

_ROAST_MESSAGES = [
    "Bekorchimisiz? Ishlasez bo'lmaydimi? 😒",
    "Nima, qizlarning videosini yuklab olayapsizmi? 👀",
    "Vaqtingiz ko'p ekan-da, tabriklayman...",
    "Instagram o'zida ko'rsang bo'lmasmidi, endi bot ham kerakmi? 🙄",
    "Yuklanmoqda... siz esa hayotingizni sovurmoqdasiz 💀",
    "Ish yo'qmi? Ish bo'lsa shu vaqtda bot bilan o'tirasizmi?",
    "Uyalinge, onangiz ko'rsa nima deydi hozir qilayotganingizni...",
    "Bir kunda nechta video yuklab olasiz o'zi? Statistika yig'yapmiz 🕵️",
    "Bu video shunchalik muhimmi hayotingizda? 😂",
    "Mana shu video uchun vaqt topding, lekin sport qilishga yo'q 🏃",
    "Telefon xotirangiz yetadimi o'zi? Savol qo'yildi.",
    "Reels ko'rish kasalligingiz bor, bilasizmi? 🏥",
    "Yetmish yil yashab shu videoni yuklab oldim deysizmi oxirida? 🤔",
    "Wi-Fi pulini to'layapsizmi hech bo'lmasa? Yo u ham boshqaning hisobidanmi?",
    "Shu videoni do'stlaringga yuborganingizda ular nima deydi deb o'ylaysiz?",
    "Ishdan bo'shab qoldingizmi yoki ish vaqtida qilyapsizmi buni? Ikkalasi ham yomon 😅",
    "Yuklanmoqda... xuddi hayotingizdagi imkoniyatlar kabi sekin ⏳",
    "Nechta reels ko'rsangiz shuncha IQ pasayadi, tadqiqotlar shuni ko'rsatmoqda 📉",
    "Qo'lingizni qarang — telefon ushlagandan egri bo'lib ketgan 📱",
    "Bu botni og'ir mehnat bilan yasadim, siz esa shu ishga ishlatyapsiz...",
    "Vaqtingizni kitob o'qishga sarflasangiz bo'lmasmidi? Lekin mayliya 📚",
    "Yuklanmoqda... siz esa hali ham o'sha o'tirishdasiz 🪑",
    "Obuna bo'lish tugmasi bor edi-ku Instagramda, u yetmasmidi? 😤",
    "Yana siz! Bugun nechanchi marta? Hisobni yo'qotdim allaqachon 🤦",
]


async def _do_download(url: str, update: Update) -> None:
    roast = random.choice(_ROAST_MESSAGES)
    status_msg = await update.message.reply_text(f"{roast}\n\n⏬ Yuklanmoqda...")

    os.makedirs(_TMPDIR, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=_TMPDIR) as tmpdir:
        ydl_opts = {
            "outtmpl": os.path.join(tmpdir, "%(id)s.%(ext)s"),
            "format": "best[ext=mp4]/best",
            "quiet": True,
            "no_warnings": True,
            "extractor_retries": 3,
            "http_headers": {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            },
        }
        def _run_ydl():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                return ydl.prepare_filename(info)

        try:
            filepath = await asyncio.to_thread(_run_ydl)

            if not os.path.exists(filepath):
                candidates = os.listdir(tmpdir)
                if not candidates:
                    raise FileNotFoundError("Video fayli topilmadi.")
                filepath = os.path.join(tmpdir, candidates[0])

            size = os.path.getsize(filepath)
            if size > _MAX_BYTES:
                await status_msg.edit_text(
                    f"Video juda katta ({size // (1024*1024)} MB). "
                    "Telegram 50 MB dan katta fayllarni qabul qilmaydi."
                )
                return

            with open(filepath, "rb") as video_file:
                await update.message.reply_video(
                    video=video_file,
                    supports_streaming=True,
                    read_timeout=120,
                    write_timeout=120,
                )
            await status_msg.delete()

        except yt_dlp.utils.DownloadError as exc:
            logger.warning("yt-dlp download error for %s: %s", url, exc)
            await status_msg.edit_text(
                f"Video yuklab bo'lmadi.\n\n<code>{exc}</code>",
                parse_mode="HTML",
            )
        except Exception as exc:
            logger.error("Unexpected error downloading %s: %s", url, exc)
            await status_msg.edit_text(
                f"Xatolik yuz berdi.\n\n<code>{type(exc).__name__}: {exc}</code>",
                parse_mode="HTML",
            )


async def auto_download(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text or ""
    match = _SUPPORTED_RE.search(text)
    if match:
        await _do_download(match.group(), update)
