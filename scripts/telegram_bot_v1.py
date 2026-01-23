#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = [
#   "pudb", "ipython",
#   "pillow>=11.1.0",
#   "telethon>=1.42.0",
#   "python-telegram-bot>=22.5",
#   "python-dateutil",
# ]
# ///
"""
Implements a telegram bot for freiheitliche-stammtische.de.

Uses the following environment variables:
    FSTISCH_BOT_TOKEN

Usage:
    ./scripts/telegram_bot.py register-chat [OPTIONS]
    ./scripts/telegram_bot.py chat-info [OPTIONS]
    ./scripts/telegram_bot.py listen [OPTIONS]

Options:
    -c --chat-id <chat-id>  Chat ID to register
    -v, --verbose           Enable verbose logging
    -q, --quiet             Enable quiet logging
    -h, --help              Show this help message and exit
"""
import os
import re
import sys
import json
import uuid
import time
import logging
import pathlib as pl
import datetime as dt
import zoneinfo as zi

TZ_BERLIN = zi.ZoneInfo("Europe/Berlin")

from utils import cli

log = logging.getLogger('telegram_bot')

API_ID = os.environ.get('FSTISCH_API_ID')
API_HASH = os.environ.get('FSTISCH_API_HASH')
assert API_ID, "missing envvar: FSTISCH_API_ID"
assert API_HASH, "missing envvar: FSTISCH_API_HASH"

BOT_ID = 'freiheitliche-stammtische-sync'
BOT_NAME = "@FreiheitlicheStammtischeBot"
BOT_TOKEN = os.environ.get('FSTISCH_BOT_TOKEN')

assert BOT_TOKEN, "missing envvar: FSTISCH_BOT_TOKEN"

STATE_FILE = pl.Path("data") / "telegram_bot.json"


def _load_state() -> dict:
    if not STATE_FILE.exists():
        return {"users": {}, "groups": {}, "channels": {}}

    with STATE_FILE.open(mode="r", encoding="utf-8") as fobj:
        try:
            return json.load(fobj)
        except json.JSONDecodeError:
            return {"users": {}, "groups": {}, "channels": {}}


def _save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp_path = STATE_FILE.with_suffix(f".tmp-{uuid.uuid4().hex}")
    with temp_path.open(mode="w", encoding="utf-8") as fobj:
        json.dump(state, fobj, indent=2, ensure_ascii=False)
    temp_path.replace(STATE_FILE)


async def get_chats(bot: "telegram.Bot"):
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


def _update_state_from_chat(state: dict, chat: "telegram.Chat") -> None:
    if not chat:
        return

    chat_id = str(chat.id)
    info = {
        "id": chat.id,
        "type": chat.type,
        "title": getattr(chat, 'title', None),
        "username": getattr(chat, 'username', None),
        "first_name": getattr(chat, 'first_name', None),
        "last_name": getattr(chat, 'last_name', None),
        "last_seen": dt.datetime.now(TZ_BERLIN).isoformat()
    }

    if "users" not in state:
        state["users"] = {}
    if "groups" not in state:
        state["groups"] = {}
    if "channels" not in state:
        state["channels"] = {}

    if chat.type in ("group", "supergroup"):
        state["groups"][chat_id] = info
    elif chat.type == "channel":
        state["channels"][chat_id] = info
    else:
        state["users"][chat_id] = info


def _update_state_from_update(state: dict, update: 'telegram.Update') -> None:
    # Exhaustively look for any chat object in the update
    chat = None
    sources = [
        update.effective_chat,
        update.message.chat if update.message else None,
        update.edited_message.chat if update.edited_message else None,
        update.my_chat_member.chat if update.my_chat_member else None,
        update.chat_member.chat if update.chat_member else None,
        update.channel_post.chat if update.channel_post else None,
        update.edited_channel_post.chat if update.edited_channel_post else None,
        update.callback_query.message.chat if (update.callback_query and update.callback_query.message) else None,
        update.chat_join_request.chat if update.chat_join_request else None,
        update.chat_boost.chat if update.chat_boost else None,
        update.removed_chat_boost.chat if update.removed_chat_boost else None,
    ]
    
    for s in sources:
        if s:
            chat = s
            break

    if chat:
        msg = f"   >> Discovered {chat.type}: {getattr(chat, 'title', chat.username or chat.id)} (ID: {chat.id})"
        print(msg)
        log.info(msg)
        _update_state_from_chat(state, chat)
    else:
        # Log update structure for debugging if no chat found
        print(f"   !! Update {update.update_id} contains no identifiable chat info. Fields: {list(update.to_dict().keys())}")


EVENTS_FILE = pl.Path("data") / "telegram_events.json"


def _save_event(event_info: dict) -> None:
    events = []
    if EVENTS_FILE.exists():
        with EVENTS_FILE.open("r", encoding="utf-8") as f:
            try:
                events = json.load(f)
            except json.JSONDecodeError:
                pass
    
    events.append(event_info)
    
    with EVENTS_FILE.open("w", encoding="utf-8") as f:
        json.dump(events, f, indent=2, ensure_ascii=False)


def extract_event_info(text: str) -> dict | None:
    if not text:
        return None

    # Regex for Date: dd.mm.yyyy or dd.mm.
    date_pattern = r"(\d{1,2})\.(\d{1,2})\.(\d{2,4})?"
    # Regex for Time: HH:MM
    time_pattern = r"(\d{1,2}):(\d{2})"

    date_match = re.search(date_pattern, text)
    time_match = re.search(time_pattern, text)

    if not date_match:
        return None

    day = int(date_match.group(1))
    month = int(date_match.group(2))
    year_str = date_match.group(3)

    now = dt.datetime.now(TZ_BERLIN)
    year = int(year_str) if year_str else now.year
    
    # Adjust 2-digit year
    if year < 100:
        year += 2000

    try:
        # Handle implicit next year if date is in the past (only if year wasn't specified)
        if not year_str and dt.date(year, month, day) < now.date():
             year += 1
        
        event_date = dt.date(year, month, day)
    except ValueError:
        return None

    hour = 19
    minute = 0
    if time_match:
        hour = int(time_match.group(1))
        minute = int(time_match.group(2))

    return {
        "date": event_date.isoformat(),
        "time": f"{hour:02d}:{minute:02d}",
        "original_text": text[:200]
    }


async def create_poll_command(update: 'telegram.Update', context: 'txt.ContextTypes.DEFAULT_TYPE') -> None:
    """Sends a poll to vote on the next meeting date."""
    chat = update.effective_chat
    now = dt.datetime.now(TZ_BERLIN)
    
    # Generate next 4 options (e.g., next 4 Fridays if today is Friday, or just next 4 weeks from now)
    # Defaulting to the same weekday as today for simplicity, or just next 4 days if user wants?
    # Context implies "when the next event should be". 
    # Usually Stammtisch is on a specific weekday. Let's offer the next 4 occurrences of the current weekday.
    
    current_weekday = now.weekday()
    options = []
    
    for i in range(1, 5):
        # simple: +1 week
        delta = dt.timedelta(weeks=i)
        future_date = now + delta
        # Align to same weekday if needed, but 'weeks=i' keeps weekday unless logic changes.
        # Actually better to find "next Friday" etc. if explicitly asked, but here we guess.
        # Let's try to be smart: if they ask on a Monday, maybe they want the next Monday?
        
        # Format: "Fri, 24.01."
        label = future_date.strftime(f"%a, %d.%m.")
        options.append(label)

    message = await context.bot.send_poll(
        chat_id=chat.id,
        question="Wann soll der nächste Stammtisch stattfinden?",
        options=options,
        is_anonymous=False,
        allows_multiple_answers=True,
    )
    
    # Save poll info context if needed, but txt.PollAnswerHandler handles responses stateless mostly.
    payload = {
        message.poll.id: {
            "chat_id": chat.id,
            "message_id": message.message_id,
            "created_at": now.isoformat(),
        }
    }
    context.bot_data.update(payload)


async def handle_poll_answer(update: 'telegram.Update', context: 'txt.ContextTypes.DEFAULT_TYPE') -> None:
    answer = update.poll_answer
    poll_id = answer.poll_id
    user = answer.user
    option_ids = answer.option_ids
    
    print(f"Poll {poll_id}: User {user.first_name} voted for {option_ids}")


async def handle_any_message(update: 'telegram.Update', context: 'txt.ContextTypes.DEFAULT_TYPE') -> None:
    state = _load_state()
    _update_state_from_update(state, update)
    _save_state(state)
    
    msg = update.message or update.edited_message
    if not msg:
        return

    text = msg.text or msg.caption or ""
    
    # 1. Pinned Message Detection
    if msg.pinned_message:
        print(f"Pinned message detected in {msg.chat.title}")
        text = msg.pinned_message.text or msg.pinned_message.caption or ""
        # Process as event candidate

    # 2. Forwarded Message Detection (in private chat)
    if msg.chat.type == "private" and (msg.forward_origin or msg.forward_from or msg.forward_from_chat):
         print(f"Forwarded message detected from {msg.from_user.first_name}")
         # Process as event candidate

    # Attempt to extract event info
    event_info = extract_event_info(text)
    if event_info:
        # Check if we should ignore (e.g. already processed, or bot's own poll msg - though unlikely here)
        print(f"Potential event found: {event_info}")
        
        context.user_data['pending_event'] = event_info
        
        # Build confirmation message
        date_str = event_info['date']
        time_str = event_info['time']
        
        reply_text = (
            f"📅 <b>Event erkannt!</b>\n\n"
            f"Datum: {date_str}\n"
            f"Zeit: {time_str}\n\n"
            f"Soll ich diesen Termin speichern?"
        )
        
        keyboard = [
            [
                telegram.InlineKeyboardButton("✅ Ja, speichern", callback_data="confirm_event"),
                telegram.InlineKeyboardButton("❌ Abbrechen", callback_data="cancel_event"),
            ]
        ]
        
        await msg.reply_text(reply_text, reply_markup=telegram.InlineKeyboardMarkup(keyboard), parse_mode="HTML")


async def handle_callback(update: 'telegram.Update', context: 'txt.ContextTypes.DEFAULT_TYPE') -> None:
    query = update.callback_query
    await query.answer()
    
    if query.data == "confirm_event":
        event_info = context.user_data.get('pending_event')
        if event_info:
            _save_event(event_info)
            await query.edit_message_text(text=f"✅ Termin am {event_info['date']} um {event_info['time']} wurde gespeichert!")
            print(f"Saved event: {event_info}")
        else:
            await query.edit_message_text(text="⚠️ Fehler: Keine Event-Daten gefunden (Session abgelaufen?).")
            
    elif query.data == "cancel_event":
        context.user_data.pop('pending_event', None)
        await query.edit_message_text(text="❌ Vorgang abgebrochen.")


async def help_command(update: 'telegram.Update', context: 'txt.ContextTypes.DEFAULT_TYPE') -> None:
    user = update.effective_user
    await update.message.reply_text(
        f"Hi {user.mention_html()}! \n"
        "Use /"
    )


def run_bot():
    import telegram
    import telegram.ext as txt

    termine_by_gid = _load_termine_by_gid()

    app = txt.Application.builder().token(BOT_TOKEN).build()
    # Track all chats and groups
    app.add_handler(txt.MessageHandler(txt.filters.ALL, handle_any_message), group=-1)


    app.add_handler(txt.CommandHandler("create_poll", create_poll_command))
    app.add_handler(txt.PollAnswerHandler(handle_poll_answer))
    app.add_handler(txt.CallbackQueryHandler(handle_callback))

    app.add_handler(txt.CommandHandler(["start", "help", "commands"], help_command))

    # Run the bot until the user presses Ctrl-C
    app.run_polling(allowed_updates=telegram.Update.ALL_TYPES)


_cli_defaults = {
    "--chat-id": None,
}


def init_telethon_client() -> "telethon.TelegramClient":
    import telethon
    # We use a bot session name to distinguish it from a user session if needed
    client = telethon.TelegramClient('freiheitliche-stammtische-app', API_ID, API_HASH)
    return client


async def _resolve_entity(client: "telethon.TelegramClient", chat_id_str: str) -> "telethon.types.TypeEntity":
    import telethon.types as ttypes
    
    # 1. Try direct lookup (smartest)
    try:
        raw_id = int(chat_id_str)
        return await client.get_entity(raw_id)
    except (ValueError, Exception):
        pass

    # 2. Try common transformations if direct failed
    try:
        raw_id = int(chat_id_str)
        abs_id = abs(raw_id)
        lookups = []
        
        if chat_id_str.startswith("-100"):
            # Definitely a Channel/Supergroup
            lookups.append(ttypes.PeerChannel(int(chat_id_str[4:])))
        elif raw_id < 0:
            # Could be a Basic Group OR a Supergroup missing the prefix
            lookups.append(ttypes.PeerChannel(abs_id))
            lookups.append(ttypes.PeerChat(abs_id))
        else:
            # Likely a User or positive Channel ID
            lookups.append(ttypes.PeerUser(raw_id))
            lookups.append(ttypes.PeerChannel(raw_id))

        for peer in lookups:
            try:
                entity = await client.get_entity(peer)
                if entity:
                    return entity
            except Exception:
                continue
    except ValueError:
        # String username or other
        return await client.get_entity(chat_id_str)
    
    return None


async def register_chat_command(chat_id_str: str) -> None:
    from telethon import types
    
    state = _load_state()
    client = init_telethon_client()
    
    # Telethon needs to be started with the BOT_TOKEN to act as a bot
    await client.start(bot_token=BOT_TOKEN)
    
    async with client:
        print(f"Searching for chat ID: {chat_id_str}...")
        try:
            entity = await _resolve_entity(client, chat_id_str)

            if not entity:
                raise ValueError(f"Could not resolve entity for ID: {chat_id_str}. "
                                 "If it is a private group, the bot might need to be a member first.")

            # Update state manually from Telethon entity
            chat_id_key = str(getattr(entity, 'id', chat_id_str))
            
            # Determine type
            chat_type = "unknown"
            if isinstance(entity, types.User):
                chat_type = "private"
            elif isinstance(entity, (types.Chat, types.ChatFull, types.PeerChat)):
                chat_type = "group"
            elif isinstance(entity, (types.Channel, types.ChannelFull, types.PeerChannel)):
                # Megagroups are Channels in Telethon/MTProto
                if getattr(entity, 'broadcast', False):
                    chat_type = "channel"
                else:
                    chat_type = "supergroup"

            info = {
                "id": entity.id,
                "type": chat_type,
                "title": getattr(entity, 'title', None),
                "username": getattr(entity, 'username', None),
                "first_name": getattr(entity, 'first_name', None),
                "last_name": getattr(entity, 'last_name', None),
                "last_seen": dt.datetime.now(TZ_BERLIN).isoformat()
            }

            if chat_type in ("group", "supergroup"):
                state["groups"][chat_id_key] = info
            elif chat_type == "channel":
                state["channels"][chat_id_key] = info
            else:
                state["users"][chat_id_key] = info

            print(f"Found {chat_type}: {info['title'] or info['username'] or chat_id_key}")
            _save_state(state)
            print(f"Successfully registered and saved to {STATE_FILE}")
            
            # Fetch recent messages (best effort)
            try:
                print("\nRecent messages:")
                message_count = 0
                async for message in client.iter_messages(entity, limit=10):
                    date_str = message.date.strftime("%Y-%m-%d %H:%M:%S")
                    sender = "Unknown"
                    if message.sender:
                       sender = getattr(message.sender, 'title', getattr(message.sender, 'username', 'Unknown'))
                    
                    text = (message.text or "[No text content]").replace('\n', ' ')[:80]
                    print(f"  [{date_str}] {sender}: {text}...")
                    message_count += 1
                
                if message_count == 0:
                    print("  (No recent messages found or accessible)")
            except Exception as e:
                print(f"  (Note: Could not fetch messages: {e})")
                log.debug(f"History fetch restricted for {chat_id_key}: {e}")

        except Exception as e:
            print(f"Error registering chat: {e}")
            log.exception("Registration failed")


async def chat_info_command() -> None:
    from telethon import types
    
    state = _load_state()
    client = init_telethon_client()
    
    # Start client as bot
    await client.start(bot_token=BOT_TOKEN)
    
    async with client:
        print("Refreshing info for all known chats...")
        
        updated = False
        all_chats = []
        for category in ("users", "groups", "channels"):
            for chat_id, info in state.get(category, {}).items():
                all_chats.append((category, chat_id, info))
        
        if not all_chats:
            print("No chats registered yet. Use register-chat --chat-id <id> first.")
            return

        for category, chat_id_str, info in all_chats:
            try:
                entity = await _resolve_entity(client, chat_id_str)
                if not entity:
                    print(f"  [Error] Could not resolve {category[:-1]} {chat_id_str}")
                    continue
                
                # Update info
                info["title"] = getattr(entity, 'title', None)
                info["username"] = getattr(entity, 'username', None)
                info["first_name"] = getattr(entity, 'first_name', None)
                info["last_name"] = getattr(entity, 'last_name', None)
                info["last_seen"] = dt.datetime.now(TZ_BERLIN).isoformat()
                
                print(f"  [Refreshed] {category[:-1].capitalize()}: {info['title'] or info['username'] or chat_id_str}")
                updated = True
            except Exception as e:
                print(f"  [Error] Could not refresh {category[:-1]} {chat_id_str}: {e}")

        if updated:
            _save_state(state)
        
        print("\n--- Current State ---")
        print(json.dumps(state, indent=2, ensure_ascii=False))


def main(argv: list[str] = sys.argv[1:]) -> int:
    subcmd, args = cli.parse_args(argv, doc=__doc__, defaults=_cli_defaults)

    if subcmd not in ("register-chat", "chat-info", "listen"):
        print(__doc__)
        return 1

    logging.getLogger("httpx").setLevel(logging.WARNING)
    cli.init_logging(args)

    if subcmd == "register-chat":
        chat_id = args.chat_id
        if not chat_id:
            print("Error: --chat-id is required for register-chat")
            return 1
        
        import asyncio
        asyncio.run(register_chat_command(chat_id))
        return 0

    if subcmd == "chat-info":
        import asyncio
        asyncio.run(chat_info_command())
        return 0

    if subcmd == "listen":
        run_bot()
        return 0

    # import asyncio
    # import telegram
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

    return 1

if __name__ == '__main__':
    sys.exit(main())
