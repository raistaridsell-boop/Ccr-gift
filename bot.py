import os
import asyncio
import sqlite3
from contextlib import closing
from typing import Optional

from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatMemberStatus
from telegram.request import HTTPXRequest
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
OWNER_ID = int(os.getenv("OWNER_ID", "0") or "0")
DATABASE_PATH = os.getenv("DATABASE_PATH", "bot.db").strip()

ENTER_KEY = 1


def db() -> sqlite3.Connection:
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_database() -> None:
    with closing(db()) as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS admins (
                user_id INTEGER PRIMARY KEY
            );
            CREATE TABLE IF NOT EXISTS gifts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                gift_key TEXT,
                content TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )
        if OWNER_ID:
            connection.execute(
                "INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (OWNER_ID,)
            )
        connection.commit()


def get_setting(key: str, default: Optional[str] = None) -> Optional[str]:
    with closing(db()) as connection:
        row = connection.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
    return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    with closing(db()) as connection:
        connection.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        connection.commit()


def is_admin(user_id: int) -> bool:
    if user_id == OWNER_ID:
        return True
    with closing(db()) as connection:
        return (
            connection.execute(
                "SELECT 1 FROM admins WHERE user_id = ?", (user_id,)
            ).fetchone()
            is not None
        )


async def remember_user(update: Update) -> None:
    user = update.effective_user
    if not user:
        return
    with closing(db()) as connection:
        connection.execute(
            "INSERT INTO users (user_id, username, first_name) VALUES (?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET "
            "username = excluded.username, first_name = excluded.first_name",
            (user.id, user.username, user.first_name),
        )
        connection.commit()


async def is_member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    channel = get_setting("channel", os.getenv("FORCE_JOIN_CHANNEL", "").strip())
    if not channel:
        return True
    user = update.effective_user
    if not user:
        return False
    try:
        member = await context.bot.get_chat_member(channel, user.id)
        return member.status in {
            ChatMemberStatus.MEMBER,
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.OWNER,
        }
    except Exception:
        return False


def join_keyboard(channel: Optional[str]) -> InlineKeyboardMarkup:
    buttons = []
    if channel:
        if channel.startswith("@"):
            link = f"https://t.me/{channel.lstrip('@')}"
        else:
            link = None
        if link:
            buttons.append([InlineKeyboardButton("📢 JOIN CHANNEL", url=link)])
    buttons.append([InlineKeyboardButton("✅ VERIFY JOIN", callback_data="verify_join")])
    return InlineKeyboardMarkup(buttons)


async def show_gifts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    with closing(db()) as connection:
        gifts = connection.execute(
            "SELECT id, name FROM gifts ORDER BY id"
        ).fetchall()

    if not gifts:
        text = "🎁 Available Gifts\n\nAbhi koi gift available nahi hai."
        keyboard = InlineKeyboardMarkup([])
    else:
        text = "🎁 Available Gifts\n\nGift select karke key enter karein:"
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton(
                f"🎁 Gift {gift['id']} — {gift['name']} (🔐 Unlock)",
                callback_data=f"gift:{gift['id']}",
            )] for gift in gifts]
        )

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text, reply_markup=keyboard)
    else:
        await update.message.reply_text(text, reply_markup=keyboard)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await remember_user(update)
    channel = get_setting("channel", os.getenv("FORCE_JOIN_CHANNEL", "").strip())
    if not await is_member(update, context):
        await update.message.reply_text(
            "Welcome to CCR Nexus Bot 🥰\n\n"
            "Our community provides methods and gifts.\n"
            "Join our channels and enjoy.",
            reply_markup=join_keyboard(channel),
        )
        return
    await show_gifts(update, context)


async def verify_join(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await remember_user(update)
    query = update.callback_query
    await query.answer()
    if await is_member(update, context):
        await show_gifts(update, context)
    else:
        channel = get_setting("channel", os.getenv("FORCE_JOIN_CHANNEL", "").strip())
        await query.edit_message_text(
            "Aapne channel join nahi kiya hai. Pehle join karein, phir verify karein.",
            reply_markup=join_keyboard(channel),
        )


async def select_gift(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await remember_user(update)
    query = update.callback_query
    await query.answer()
    gift_id = int(query.data.split(":", 1)[1])
    with closing(db()) as connection:
        gift = connection.execute(
            "SELECT id, name, gift_key, content FROM gifts WHERE id = ?", (gift_id,)
        ).fetchone()
    if not gift:
        await query.edit_message_text("Gift ab available nahi hai.")
        return ConversationHandler.END

    context.user_data["selected_gift_id"] = gift_id
    await query.edit_message_text(
        f"🎁 Gift {gift_id} selected\n\n{gift['name']}\nEnter your gift key:",
    )
    return ENTER_KEY


async def enter_key(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    gift_id = context.user_data.get("selected_gift_id")
    supplied_key = (update.message.text or "").strip()
    with closing(db()) as connection:
        gift = connection.execute(
            "SELECT name, gift_key, content FROM gifts WHERE id = ?", (gift_id,)
        ).fetchone()
    if not gift:
        await update.message.reply_text("Gift ab available nahi hai.")
        return ConversationHandler.END
    if not gift["gift_key"] or supplied_key != gift["gift_key"]:
        await update.message.reply_text(
            "Incorrect key. Please try again.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 Gift List", callback_data="gift_list")]]
            ),
        )
        return ENTER_KEY

    context.user_data.pop("selected_gift_id", None)
    await update.message.reply_text(
        f"✅ Gift unlocked: {gift['name']}\n\n"
        f"{gift['content'] or 'Congratulations! Gift successfully unlocked.'}"
    )
    return ConversationHandler.END


async def gift_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await show_gifts(update, context)
    return ConversationHandler.END


async def admin_required(update: Update) -> bool:
    if not update.effective_user or not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Aap authorized admin nahi hain.")
        return False
    return True


async def addgift(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await admin_required(update):
        return
    text = " ".join(context.args).strip()
    if not text:
        await update.message.reply_text(
            "Usage: /addgift Gift Name::Gift content"
        )
        return
    name, separator, content = text.partition("::")
    name = name.strip()
    if not name:
        await update.message.reply_text("Gift name required hai.")
        return
    with closing(db()) as connection:
        cursor = connection.execute(
            "INSERT INTO gifts (name, content) VALUES (?, ?)",
            (name, content.strip() if separator else ""),
        )
        connection.commit()
        gift_id = cursor.lastrowid
    await update.message.reply_text(
        f"✅ Gift added!\nID: {gift_id}\nName: {name}\n"
        f"Key set karne ke liye: /setkey {gift_id} YOUR_KEY"
    )


async def delgift(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await admin_required(update):
        return
    if not context.args:
        await update.message.reply_text("Usage: /delgift GIFT_ID")
        return
    try:
        gift_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Valid gift ID bhejein.")
        return
    with closing(db()) as connection:
        cursor = connection.execute("DELETE FROM gifts WHERE id = ?", (gift_id,))
        connection.commit()
    if cursor.rowcount:
        await update.message.reply_text(f"✅ Gift {gift_id} delete ho gaya.")
    else:
        await update.message.reply_text("Gift nahi mila.")


async def setkey(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await admin_required(update):
        return
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /setkey GIFT_ID KEY")
        return
    try:
        gift_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Valid gift ID bhejein.")
        return
    key = " ".join(context.args[1:]).strip()
    with closing(db()) as connection:
        cursor = connection.execute(
            "UPDATE gifts SET gift_key = ? WHERE id = ?", (key, gift_id)
        )
        connection.commit()
    if cursor.rowcount:
        await update.message.reply_text(f"✅ Gift {gift_id} ki key set ho gayi.")
    else:
        await update.message.reply_text("Gift nahi mila.")


async def addadmin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await admin_required(update):
        return
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ Sirf owner admin add kar sakta hai.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /addadmin USER_ID")
        return
    try:
        user_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Valid Telegram user ID bhejein.")
        return
    with closing(db()) as connection:
        connection.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (user_id,))
        connection.commit()
    await update.message.reply_text(f"✅ Admin added: `{user_id}`", parse_mode="Markdown")


async def setchannel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await admin_required(update):
        return
    if not context.args:
        await update.message.reply_text("Usage: /setchannel @channel_username")
        return
    channel = context.args[0].strip()
    set_setting("channel", channel)
    await update.message.reply_text(
        f"✅ Force join channel set: {channel}\n"
        "Bot ko channel mein admin add karna zaroori hai."
    )


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await admin_required(update):
        return
    with closing(db()) as connection:
        users = connection.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        gifts = connection.execute("SELECT COUNT(*) FROM gifts").fetchone()[0]
        admins = connection.execute("SELECT COUNT(*) FROM admins").fetchone()[0]
    await update.message.reply_text(
        f"📊 Bot Stats\n\n👥 Total users: {users}\n"
        f"🎁 Total gifts: {gifts}\n👮 Admins: {admins}"
    )


async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await admin_required(update):
        return
    message = " ".join(context.args).strip()
    if not message:
        await update.message.reply_text("Usage: /broadcast Your message")
        return
    with closing(db()) as connection:
        user_ids = [
            row["user_id"]
            for row in connection.execute("SELECT user_id FROM users").fetchall()
        ]
    sent = 0
    blocked = 0
    for user_id in user_ids:
        try:
            await context.bot.send_message(chat_id=user_id, text=message)
            sent += 1
        except Exception:
            blocked += 1
    await update.message.reply_text(
        f"📣 Broadcast complete\n✅ Sent: {sent}\n❌ Failed/blocked: {blocked}"
    )


async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Available command nahi mila. /start se gift list dekhein."
    )


def main() -> None:
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN environment variable is required")
    initialize_database()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    request = HTTPXRequest(connect_timeout=30, read_timeout=30, write_timeout=30)
    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .request(request)
        .get_updates_request(request)
        .build()
    )
    gift_conversation = ConversationHandler(
        entry_points=[CallbackQueryHandler(select_gift, pattern=r"^gift:\d+$")],
        states={
            ENTER_KEY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, enter_key),
            ]
        },
        fallbacks=[CallbackQueryHandler(gift_list, pattern=r"^gift_list$")],
        per_message=False,
    )
    application.add_handler(gift_conversation)
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(verify_join, pattern=r"^verify_join$"))
    application.add_handler(CommandHandler("addgift", addgift))
    application.add_handler(CommandHandler("delgift", delgift))
    application.add_handler(CommandHandler("setkey", setkey))
    application.add_handler(CommandHandler("addadmin", addadmin))
    application.add_handler(CommandHandler("setchannel", setchannel))
    application.add_handler(CommandHandler("broadcast", broadcast))
    application.add_handler(CommandHandler("stats", stats))
    application.add_handler(MessageHandler(filters.COMMAND, unknown))

    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
