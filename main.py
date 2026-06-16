import logging
import os

from dotenv import load_dotenv
from telegram import BotCommand
from telegram.ext import Application, CommandHandler, MessageHandler, filters

from downloader import auto_download

load_dotenv()

logging.basicConfig(
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

COMMANDS = [
    BotCommand("start", "Botni ishga tushirish"),
    BotCommand("help",  "Yordam"),
]


async def start(update, context) -> None:
    await update.message.reply_text(
        "<b>InstaVideo Yuklagich Boti</b>\n\n"
        "Instagram video yoki Reels havolasini yuboring — yuklab beraman!\n\n"
        "Masalan: https://www.instagram.com/reel/...",
        parse_mode="HTML",
    )


async def post_init(app: Application) -> None:
    await app.bot.set_my_commands(COMMANDS)
    logger.info("Bot commands registered.")


def main() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set. Copy .env.example to .env and fill it in.")

    app = (
        Application.builder()
        .token(token)
        .post_init(post_init)
        .read_timeout(120)
        .write_timeout(120)
        .connect_timeout(30)
        .pool_timeout(30)
        .build()
    )

    app.add_handler(CommandHandler(["start", "help"], start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, auto_download))

    logger.info("InstaVideoYuklagichBot is running. Press Ctrl-C to stop.")
    app.run_polling(allowed_updates=["message"])


if __name__ == "__main__":
    main()
