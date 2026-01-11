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

import telegram
from telegram import ForceReply, Update
from telegram.ext import Application, CommandHandler, ContextTypes

from utils import cli

log = logging.getLogger('telegram_bot')


BOT_ID = 'freiheitliche-stammtische-sync'
BOT_NAME = "@FreiheitlicheStammtischeBot"
BOT_TOKEN = os.environ.get('FSTISCH_BOT_TOKEN')

assert BOT_TOKEN, "missing envvar: FSTISCH_TELEGRAM_API_HASH"


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


async def _bot_echo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    await update.message.reply_html(
        rf"Hi {user.mention_html()}!",
        reply_markup=ForceReply(selective=True),
    )


def _run_bot():
    termine_by_gid = _load_termine_by_gid()

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler(["echo"], _bot_echo))

    # Run the bot until the user presses Ctrl-C
    app.run_polling(allowed_updates=Update.ALL_TYPES)


_cli_defaults = {
}


def main(argv: list[str] = sys.argv[1:]) -> int:
    args = cli.parse_args(argv, doc=__doc__, defaults=_cli_defaults)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    cli.init_logging(args)

    _run_bot()

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
