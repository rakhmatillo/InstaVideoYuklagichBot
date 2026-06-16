import asyncio
import json
import logging
import os
import random
import re
import shutil
import tempfile

import yt_dlp
from telegram import Update
from telegram.ext import ContextTypes

from db import upsert_user

_SUPPORTED_RE = re.compile(r"https?://(?:www\.)?instagram\.com/\S+")

logger = logging.getLogger(__name__)

_MAX_BYTES = 80 * 1024 * 1024  # 80 MB upload limit
_TMPDIR = os.path.join(os.path.dirname(__file__), "downloads")
_COOKIES_FILE = os.path.join(os.path.dirname(__file__), "cookies.txt")

_NETSCAPE_COOKIES_FILE = _COOKIES_FILE + ".converted"


def _get_cookies_path() -> str | None:
    """Return a Netscape-format cookies path, converting from JSON if needed."""
    if not os.path.exists(_COOKIES_FILE):
        return None

    with open(_COOKIES_FILE, "r", encoding="utf-8") as f:
        content = f.read().strip()

    # Already Netscape format
    if content.startswith("#") or "\t" in content[:200]:
        return _COOKIES_FILE

    # JSON format — convert to Netscape
    try:
        data = json.loads(content)
        if isinstance(data, dict):
            data = data.get("cookies", [])

        lines = ["# Netscape HTTP Cookie File"]
        for c in data:
            domain = c.get("domain", "")
            subdomains = "TRUE" if domain.startswith(".") else "FALSE"
            path = c.get("path", "/")
            secure = "TRUE" if c.get("secure", False) else "FALSE"
            expiry = int(c.get("expirationDate", c.get("expires", 0)) or 0)
            name = c.get("name", "")
            value = c.get("value", "")
            lines.append(f"{domain}\t{subdomains}\t{path}\t{secure}\t{expiry}\t{name}\t{value}")

        with open(_NETSCAPE_COOKIES_FILE, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        logger.info("Converted JSON cookies to Netscape format -> %s", _NETSCAPE_COOKIES_FILE)
        return _NETSCAPE_COOKIES_FILE

    except Exception as exc:
        logger.error("Failed to convert cookies: %s", exc)
        return None


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


async def _fix_aspect_ratio(input_path: str) -> str:
    """Re-mux video with ffmpeg to fix SAR metadata — fixes square-frame bug on iOS/macOS."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        logger.warning("ffmpeg not found — skipping aspect ratio fix (video may appear square on iOS/macOS)")
        return input_path

    base, ext = os.path.splitext(input_path)
    output_path = base + "_fixed" + (ext or ".mp4")

    proc = await asyncio.create_subprocess_exec(
        ffmpeg, "-y", "-i", input_path,
        "-vf", "setsar=1",          # fix sample aspect ratio to 1:1
        "-c:a", "copy",             # copy audio stream unchanged
        "-movflags", "+faststart",  # MP4 fast-start for streaming
        output_path,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()

    if proc.returncode == 0 and os.path.exists(output_path):
        logger.info("Aspect ratio fixed: %s", output_path)
        return output_path

    logger.warning("ffmpeg aspect ratio fix failed: %s", stderr.decode(errors="replace"))
    return input_path


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
        cookies_path = _get_cookies_path()
        cookies_loaded = cookies_path is not None
        if cookies_loaded:
            ydl_opts["cookiefile"] = cookies_path
            logger.info("Using cookies: %s", cookies_path)
        else:
            logger.warning("cookies.txt not found at %s — trying without auth", _COOKIES_FILE)

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

            filepath = await _fix_aspect_ratio(filepath)

            size = os.path.getsize(filepath)
            if size > _MAX_BYTES:
                await status_msg.edit_text(
                    f"Video juda katta ({size // (1024 * 1024)} MB). "
                    "80 MB dan katta fayllarni yuborib bo'lmaydi."
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
            err = str(exc).lower()
            if "login required" in err or "rate-limit" in err or "not available" in err:
                if not cookies_loaded:
                    msg = (
                        "❌ Instagram login talab qiladi.\n\n"
                        "Bot serverida <code>cookies.txt</code> fayli topilmadi.\n"
                        "Admin serverga cookies faylini yuklashi kerak."
                    )
                else:
                    msg = (
                        "❌ Instagram cookies eskirgan yoki bloklanган.\n\n"
                        "Admin yangi <code>cookies.txt</code> faylini yuklashi kerak."
                    )
            else:
                msg = f"❌ Video yuklab bo'lmadi.\n\n<code>{exc}</code>"
            await status_msg.edit_text(msg, parse_mode="HTML")
        except Exception as exc:
            logger.error("Unexpected error downloading %s: %s", url, exc)
            await status_msg.edit_text(
                f"❌ Xatolik yuz berdi.\n\n<code>{type(exc).__name__}: {exc}</code>",
                parse_mode="HTML",
            )


async def auto_download(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return

    user = update.effective_user
    upsert_user(
        user_id=user.id,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name,
    )

    text = update.message.text or ""
    match = _SUPPORTED_RE.search(text)
    if match:
        await _do_download(match.group(), update)
