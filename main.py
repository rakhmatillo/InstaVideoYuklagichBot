import logging
import os

from dotenv import load_dotenv
from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import db
from downloader import auto_download, _COOKIES_FILE

load_dotenv()

logging.basicConfig(
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

OWNER_ID = 49036206
USERS_PER_PAGE = 10

COMMANDS = [
    BotCommand("start", "Botni ishga tushirish"),
    BotCommand("help",  "Yordam"),
]


# ---------------------------------------------------------------------------
# /start  /help
# ---------------------------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user:
        db.upsert_user(
            user_id=user.id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
        )
    await update.message.reply_text(
        "<b>InstaVideo Yuklagich Boti</b>\n\n"
        "Instagram video yoki Reels havolasini yuboring — yuklab beraman!\n\n"
        "Masalan: https://www.instagram.com/reel/...",
        parse_mode="HTML",
    )


# ---------------------------------------------------------------------------
# Phone contact handler — captures phone when user shares contact
# ---------------------------------------------------------------------------

async def contact_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    contact = update.message.contact
    if contact and contact.user_id:
        db.upsert_user(
            user_id=contact.user_id,
            username=None,
            first_name=contact.first_name,
            last_name=contact.last_name,
            phone=contact.phone_number,
        )


# ---------------------------------------------------------------------------
# /users — owner only, paginated user list
# ---------------------------------------------------------------------------

def _build_users_page(page: int) -> tuple[str, InlineKeyboardMarkup | None]:
    users, total = db.get_users_page(page, USERS_PER_PAGE)
    total_pages = max(1, (total + USERS_PER_PAGE - 1) // USERS_PER_PAGE)

    if not users:
        return "Hali foydalanuvchilar yo'q.", None

    lines = [f"<b>Foydalanuvchilar ({total} ta) — {page}/{total_pages} sahifa</b>\n"]
    for i, u in enumerate(users, start=(page - 1) * USERS_PER_PAGE + 1):
        name_parts = filter(None, [u["first_name"], u["last_name"]])
        name = " ".join(name_parts) or "—"
        username = f"@{u['username']}" if u["username"] else "—"
        phone = u["phone"] or "—"
        lines.append(
            f"{i}. <b>{name}</b> | {username}\n"
            f"    ID: <code>{u['user_id']}</code> | 📞 {phone}\n"
            f"    🕐 {u['first_seen'][:10]}"
        )

    buttons = []
    if page > 1:
        buttons.append(InlineKeyboardButton("◀ Oldingi", callback_data=f"users:{page - 1}"))
    if page < total_pages:
        buttons.append(InlineKeyboardButton("Keyingi ▶", callback_data=f"users:{page + 1}"))

    markup = InlineKeyboardMarkup([buttons]) if buttons else None
    return "\n".join(lines), markup


async def cookiestatus_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("Bu buyruq faqat bot egasi uchun.")
        return

    if os.path.exists(_COOKIES_FILE):
        stat = os.stat(_COOKIES_FILE)
        size_kb = stat.st_size // 1024
        import datetime
        mtime = datetime.datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")
        await update.message.reply_text(
            f"✅ <b>cookies.txt topildi</b>\n"
            f"Yo'l: <code>{_COOKIES_FILE}</code>\n"
            f"Hajm: {size_kb} KB\n"
            f"O'zgartirilgan: {mtime}",
            parse_mode="HTML",
        )
    else:
        await update.message.reply_text(
            f"❌ <b>cookies.txt topilmadi</b>\n\n"
            f"Quyidagi yo'lga yuklang:\n<code>{_COOKIES_FILE}</code>\n\n"
            f"Buyruq:\n<code>scp cookies.txt user@server:{_COOKIES_FILE}</code>",
            parse_mode="HTML",
        )


async def users_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("Bu buyruq faqat bot egasi uchun.")
        return
    text, markup = _build_users_page(1)
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=markup)


async def users_page_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if update.effective_user.id != OWNER_ID:
        await query.answer("Ruxsat yo'q.")
        return
    await query.answer()
    page = int(query.data.split(":")[1])
    text, markup = _build_users_page(page)
    await query.edit_message_text(text, parse_mode="HTML", reply_markup=markup)


# ---------------------------------------------------------------------------
# Application setup
# ---------------------------------------------------------------------------

async def post_init(app: Application) -> None:
    await app.bot.set_my_commands(COMMANDS)
    logger.info("Bot commands registered.")


def main() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set.")

    db.init_db()
    logger.info("Database initialised.")

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
    app.add_handler(CommandHandler("users", users_cmd))
    app.add_handler(CommandHandler("cookiestatus", cookiestatus_cmd))
    app.add_handler(CallbackQueryHandler(users_page_callback, pattern=r"^users:\d+$"))
    app.add_handler(MessageHandler(filters.CONTACT, contact_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, auto_download))

    logger.info("InstaVideoYuklagichBot is running. Press Ctrl-C to stop.")
    app.run_polling(allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    main()
