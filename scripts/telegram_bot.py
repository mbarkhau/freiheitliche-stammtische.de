#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = [
#   "pudb", "ipython",
#   "pillow>=11.1.0",
#   "python-telegram-bot>=22.5",
# ]
# ///
"""
Implements a telegram bot for freiheitliche-stammtische.de.

Uses the following environment variables:
    TELEGRAM_BOT_NAME
    TELEGRAM_BOT_TOKEN

Usage:

    ./scripts/telegram_bot.py [-h|--help]

Options:
    -v, --verbose         Enable verbose logging
    -q, --quiet           Enable quiet logging
    -h, --help            Show this help message and exit
"""
import os
import sys
import json
import asyncio
import logging
import pathlib as pl

import re
import datetime

import telegram
from telegram import ForceReply, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters

from utils import cli

log = logging.getLogger('telegram_bot')


BOT_ID = 'freiheitliche-stammtische-sync'
BOT_NAME = "@FreiheitlicheStammtischeBot"
BOT_TOKEN = os.environ.get('FSTISCH_BOT_TOKEN')

assert BOT_TOKEN, "missing envvar: FSTISCH_BOT_TOKEN"


async def get_chats(bot: telegram.Bot):
    async with bot:
        updates = await bot.get_updates()
        return {
            u.effective_chat.id: u.effective_chat
            for u in updates
            if u.effective_chat
        }



def _load_termine_by_gid() -> dict[str, list]:
    data_path = pl.Path("data") / "termine.json"
    with data_path.open(mode='r', encoding="utf-8") as fobj:
        termine = json.load(fobj)

    termine_by_telegram_group_id = {}
    for t in termine:
        gid = t.get('telegram_group_id')
        if not gid:
            continue
        if gid not in termine_by_telegram_group_id:
            termine_by_telegram_group_id[gid] = []
        termine_by_telegram_group_id[gid].append(t)
    return termine_by_telegram_group_id


def parse_event_info(text: str) -> dict[str, str]:
    """Simple regex based parser for event details."""
    details = {}
    
    # Common labels in German and English
    patterns = {
        'name': [r"(?:Name|Treffen|Event|Stammtisch):\s*(.*)", r"^([A-Z].*)$"],
        'beginn': [r"(?:Datum|Date|Beginn):\s*([\d\.-]+)"],
        'uhrzeit': [r"(?:Uhrzeit|Zeit|Time):\s*(.*)", r"(?:^|\s)ab\s*(.*)"],
        'plz': [r"(?:PLZ|Ort|Location):\s*(\d{5})"],
    }
    
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    
    for key, patterns_list in patterns.items():
        for pattern in patterns_list:
            for line in lines:
                match = re.search(pattern, line, re.IGNORECASE)
                if match:
                    details[key] = match.group(1).strip()
                    break
            if key in details:
                break
                
    # Fallback for name if not explicitly found - use first line
    if 'name' not in details and lines:
        details['name'] = lines[0]
        
    return details


async def handle_event_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message or update.edited_message
    if not message:
        return

    print("msg ", update)

    # Check if it's a pinned message or a mention
    is_pinned = update.message.pinned_message if hasattr(update.message, 'pinned_message') else False
    # Note: pinned_message attribute in Update is not directly available like this in all types of updates.
    # We check if the message itself is a "pinned" notification or if we're triggered by active mention.
    
    text = ""
    if message.pinned_message:
        text = message.pinned_message.text or message.pinned_message.caption or ""
    elif message.text:
        text = message.text

    if not text:
        return

    # If it's a normal message, check for mentions
    if not message.pinned_message:
        bot_username = (await context.bot.get_me()).username
        if f"@{bot_username}" not in text:
            return

    event_info = parse_event_info(text)
    if not event_info:
        return

    context.user_data['pending_event'] = event_info
    
    summary = "\n".join([f"<b>{k.capitalize()}</b>: {v}" for k, v in event_info.items()])
    reply_text = f"Ich habe folgende Event-Details erkannt:\n\n{summary}\n\nIst das korrekt?"
    
    keyboard = [
        [
            InlineKeyboardButton("Ja, korrekt", callback_data="confirm_event"),
            InlineKeyboardButton("Nein, abbrechen", callback_data="cancel_event"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await message.reply_html(reply_text, reply_markup=reply_markup)


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    
    if query.data == "confirm_event":
        event_info = context.user_data.get('pending_event')
        if event_info:
            print("\n--- NEW EVENT CONFIRMED ---")
            print(json.dumps(event_info, indent=2))
            print("---------------------------\n")
            await query.edit_message_text(text="Event-Details wurden an den Terminal gesendet. Vielen Dank!")
        else:
            await query.edit_message_text(text="Keine ausstehenden Event-Details gefunden.")
    elif query.data == "cancel_event":
        context.user_data.pop('pending_event', None)
        await query.edit_message_text(text="Vorgang abgebrochen.")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    await update.message.reply_text(
        f"Hi {user.mention_html()}! \n"
        "Use /"
    )


def run_bot():
    termine_by_gid = _load_termine_by_gid()

    app = Application.builder().token(BOT_TOKEN).build()

    # Handle mentions and pinned messages
    # pinned_message is a Message attribute, but we can detect when a message is pinned via Message.pinned_message
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_event_message))
    app.add_handler(MessageHandler(filters.StatusUpdate.PINNED_MESSAGE, handle_event_message))
    
    app.add_handler(CallbackQueryHandler(handle_callback))

    app.add_handler(CommandHandler(["start", "help", "commands"], help_command))

    # Run the bot until the user presses Ctrl-C
    app.run_polling(allowed_updates=Update.ALL_TYPES)


_cli_defaults = {
}


def main(argv: list[str] = sys.argv[1:]) -> int:
    args = cli.parse_args(argv, doc=__doc__, defaults=_cli_defaults)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    cli.init_logging(args)

    run_bot()

    # bot = telegram.Bot(BOT_TOKEN)
    # chats = asyncio.run(get_chats(bot))
    # for chat_id, chat in chats.items():
    #     chat_id = str(chat_id)
    #     if chat_id not in events_by_telegram_group_id:
    #         continue
    #     if str(chat_id) in events_by_telegram_group_id:
    #         print("###", chat_id)
    #         print(events_by_telegram_group_id[chat_id])
    #     events = events_by_telegram_group_id[chat_id]

    return 0

if __name__ == '__main__':
    sys.exit(main())
