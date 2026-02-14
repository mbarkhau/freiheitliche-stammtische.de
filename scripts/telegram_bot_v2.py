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
    FSTISCH_API_ID
    FSTISCH_API_HASH

Usage:
    ./scripts/telegram_bot_v2.py new-chat --entity <entity_id> [OPTIONS]
    ./scripts/telegram_bot_v2.py history [OPTIONS]
    ./scripts/telegram_bot_v2.py listen [OPTIONS]
    ./scripts/telegram_bot_v2.py find-chat --search <query> [OPTIONS]
    ./scripts/telegram_bot_v2.py find-user --search <query> [OPTIONS]

Commands:
    new-chat           Register a new chat
    history            Print recent chat history
    listen             Listen to updates
    find-chat          Search for a chat by name to get its ID
    find-user          Search for a user by name/username

Options:
    -e --entity <entity_id>     Entity ID (Chat/Group/DM)
    -s --search <query>         Search query for find-chat
    -v, --verbose               Enable verbose logging
    -q, --quiet                 Enable quiet logging
    -h, --help                  Show this help message and exit
"""
import re
import os
import sys
import json
import uuid
import asyncio
import logging
import pathlib as pl
import datetime as dt
import zoneinfo as zi

from lib import cli

# NOTE: we use lazy import to import these modules
#   telegram, telethon

log = logging.getLogger('telegram_bot')


TZ_BERLIN = zi.ZoneInfo("Europe/Berlin")

FSTISCH_API_ID = os.environ.get('FSTISCH_API_ID')
FSTISCH_API_HASH = os.environ.get('FSTISCH_API_HASH')
FSTISCH_BOT_TOKEN = os.environ.get('FSTISCH_BOT_TOKEN')
FSTISCH_APP_TITLE = os.environ.get('FSTISCH_APP_TITLE', 'freiheitliche-stammtische-app')


STATE_FILE = pl.Path("data") / "telegram_bot.json"


def _load_state(path: pl.Path) -> dict:
    if not path.exists():
        return {}

    with path.open(mode="r", encoding="utf-8") as fobj:
        try:
            return json.load(fobj)
        except json.JSONDecodeError:
            return {}


def _save_state(state: dict, path: pl.Path) -> None:
    state_text = cli.json_dumps_pretty(state)

    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(f".tmp-{uuid.uuid4().hex}")
    with temp_path.open(mode="w", encoding="utf-8") as fobj:
        fobj.write(state_text)
    temp_path.replace(path)


# helpers implementing lazy imports

_CLIENT: "telethon.TelegramClient" = None


def init_telethon_client() -> "telethon.TelegramClient":
    global _CLIENT

    if _CLIENT is None:
        import telethon
        _CLIENT = telethon.TelegramClient(FSTISCH_APP_TITLE, FSTISCH_API_ID, FSTISCH_API_HASH)
    return _CLIENT


def _load_known_chat_ids() -> list[int]:
    """Load known chat IDs from data/telegram_bot.json"""
    state = _load_state(path=STATE_FILE)
    return list(state['chats'].keys())


async def _resolve_entity(client: "telethon.TelegramClient", chat_id_str: str) -> "telethon.types.TypeEntity":
    # 1. Try direct lookup (smartest)
    try:
        raw_id = int(chat_id_str)
        return await client.get_entity(raw_id)
    except (ValueError, Exception):
        log.warning(f"Direct resolution for entity ID failed: {chat_id_str}")

    # 2. Try common transformations if direct failed
    try:
        raw_id = int(chat_id_str)
        abs_id = abs(raw_id)
        lookups = []
        import telethon.types as ttypes
        
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


def _parse_poll(msg) -> dict | None:
    media = msg.media
    if not (media and hasattr(media, 'poll') and hasattr(media.poll, 'question')):
        return None

    poll = media.poll
    # Handle TextWithEntities for question and answers
    question_text = poll.question.text if hasattr(poll.question, 'text') else str(poll.question)

    options = []
    for a in poll.answers:
        answer_text = a.text.text if hasattr(a.text, 'text') else str(a.text)
        # Encode option bytes to string/hex if needed for JSON?
        # Telethon option is bytes. json.dump fails on bytes too.
        # Let's decode if accessible, or hex.
        option_val = a.option
        if isinstance(option_val, bytes):
            # Hex string is safer for JSON
            option_val = option_val.hex()
        options.append({"text": answer_text, "option": str(option_val)})

    # Try to get results if available
    results = []
    total_voters = 0
    if hasattr(media, 'results') and media.results:
        total_voters = media.results.total_voters
        if media.results.results:
            for r in media.results.results:
                res_option_val = r.option
                if isinstance(res_option_val, bytes):
                    res_option_val = res_option_val.hex()
                results.append({"option": str(res_option_val), "voters": r.voters})

    return {
        "id": poll.id,
        "question": question_text,
        "options": options,
        "total_voters": total_voters,
        "results": results
    }


def parse_event_info(text: str) -> dict | None:
    if not text:
        return None

    # Regex for Date: dd.mm.yyyy or dd.mm. or yyyy-mm-dd
    date_pattern = r"(\d{4}-\d{2}-\d{2})|(\d{1,2})\.(\d{1,2})\.(\d{2,4})?"
    # Regex for Time: HH:MM or "19 Uhr"
    time_pattern = r"\b((\d{1,2}):(\d{2}))\b|\b(\d{1,2})\s{0,2}Uhr\b"
    # Regex for PLZ (5 digits)
    plz_pattern = r"\b(\d{5})\b"

    date_match = re.search(date_pattern, text)
    time_match = re.search(time_pattern, text)
    plz_match = re.search(plz_pattern, text)

    # If no date, it's probably not an event we can easily process
    if not date_match:
        return None

    day, month, year = None, None, None
    if date_match.group(1):
        # yyyy-mm-dd
        year, month, day = map(int, date_match.group(1).split('-'))
    else:
        # dd.mm.[yyyy]
        day = int(date_match.group(2))
        month = int(date_match.group(3))
        year_str = date_match.group(4)
        
        now = dt.datetime.now(TZ_BERLIN)
        year = int(year_str) if year_str else now.year
        if year < 100:
            year += 2000
        
        # Adjust next year if date is in the past
        try:
            if not year_str and dt.date(year, month, day) < now.date():
                year += 1
        except ValueError:
            pass

    try:
        event_date = dt.date(year, month, day)
    except (ValueError, TypeError):
        return None

    # Time extraction
    time_str = "19:00" # Default
    if time_match:
        if time_match.group(1): # HH:MM
            time_str = time_match.group(1)
        elif time_match.group(4): # X Uhr
            time_str = f"{int(time_match.group(4)):02d}:00"

    # Name extraction: Try to find "Stammtisch" or "Event" or first line
    lines = [L.strip() for L in text.split('\n') if L.strip()]
    name = "Unbekanntes Event"
    for line in lines:
        if "stammtisch" in line.lower() or "event:" in line.lower() or "treffen:" in line.lower():
            # Clean up labels
            clean_line = re.sub(r'^(Event|Treffen|Stammtisch|Nächstes Treffen):\s*', '', line, flags=re.IGNORECASE)
            name = clean_line.strip()
            break
    else:
        if lines:
            name = lines[0]

    return {
        "name": name,
        "beginn": event_date.isoformat(),
        "uhrzeit": time_str,
        "plz": plz_match.group(1) if plz_match else None,
    }


def _save_event(chat_id: str, event_info: dict) -> None:
    state = _load_state(path=STATE_FILE)
    if 'events' not in state:
        state['events'] = {}
    if chat_id not in state['events']:
        state['events'][chat_id] = []

    # Check for duplicates (same date and name)
    events = state['events'][chat_id]
    for existing in events:
        if existing.get('beginn') == event_info['beginn'] and existing.get('name') == event_info['name']:
            log.info(f"Event already exists: {event_info['name']} on {event_info['beginn']}")
            return

    events.append(event_info)
    events.sort(key=lambda x: x['beginn'])
    state['events'][chat_id] = events
    
    _save_state(state, path=STATE_FILE)


def _iter_records(recent_msgs, history_map):
    for msg in reversed(recent_msgs):
        if msg.text and "Limburg" in msg.text:
            print("######################")
            print(getattr(msg, 'reply_to_top_id', None))
            print(getattr(msg.reply_to, 'reply_to_top_id', None))
            print("######################")
            breakpoint()

        if msg.id in history_map:
            continue

        if not (msg.text or msg.media):
            continue

        if msg.sender and msg.sender.id:
            sender = getattr(msg.sender, 'first_name', getattr(msg.sender, 'username', 'Unknown'))
            sender_id = msg.sender.id
        else:
            continue

        record = {
            "id": msg.id,
            "date": msg.date.isoformat(),
            "sender_id": sender_id,
            "sender_name": sender,
            "text": msg.text,
        }

        if msg.reply_to and getattr(msg.reply_to, 'reply_to_top_id', None):
            record["topic_id"] = msg.reply_to.reply_to_top_id

        event_info = parse_event_info(msg.text)
        if event_info:
            record["event"] = event_info

        poll = _parse_poll(msg)
        if poll:
            record["text"] = f"[Poll] {poll['question']}"
            record["poll"] = poll

        yield record


async def print_recent_chat_messages(chat_ids: list[int] | None = None) -> None:
    if chat_ids is None:
        chat_ids = _load_known_chat_ids()
    
    if not chat_ids:
        log.info("No chat IDs provided or found in data/telegram_bot.json. Skipping history fetch.")
        return

    log.info(f"Fetching recent messages for {len(chat_ids)} chats via Telethon...")

    # Update state with fetched history
    state = _load_state(path=STATE_FILE)
    if "history" not in state:
        state["history"] = {}

    client = init_telethon_client()

    try:
        async with client:
            for chat_id in chat_ids:
                existing_history = state["history"].get(str(chat_id), [])
                history_map = {msg["id"]: msg for msg in existing_history}

                try:
                    # Resolve entity using robust helper
                    entity = await _resolve_entity(client, str(chat_id))
                    if not entity:
                        log.warning(f"Could not resolve entity for ID: {chat_id}")
                        continue

                    chat_title = getattr(entity, 'title', getattr(entity, 'username', str(chat_id)))

                    # Fetch last 10 messages
                    recent_msgs = []
                    async for msg in client.iter_messages(entity, limit=50):
                        recent_msgs.append(msg)
                    
                    new_records = list(_iter_records(recent_msgs, history_map))
                    if recent_msgs:
                        log.info(f"--- {len(new_records):>2} new messages in {chat_id:>11} - {chat_title} ---")
                    else:
                        log.info(f"--- No new messages in {chat_id:>11} - {chat_title} ---")
                        continue

                    for record in new_records:
                        log.info(f"  [{record['date']}] {record['sender_name']}: {repr(record['text'])[:120]}")
                        history_map[record["id"]] = record

                    state["history"][str(chat_id)] = sorted(history_map.values(), key=lambda x: x["date"])
                    _save_state(state, path=STATE_FILE)
                    
                except Exception as ex:
                    log.warning(f"Could not fetch history for {chat_id}: {ex}")
                    raise
    except Exception as ex:
        log.error(f"Failed to fetch history session: {ex}")
        raise
    finally:
        await client.disconnect()


def history_command(args) -> None:
    asyncio.run(print_recent_chat_messages())


async def listen_any(update: 'telegram.Update', context: 'tgext.ContextTypes.DEFAULT_TYPE') -> None:
    """Logs all messages it receives or which are posted to channels/groups of which the bot is a member."""
    chat = update.effective_chat
    if not chat:
        log.warning(f"Update {update.update_id} has no effective chat.")
        return

    chat_title = getattr(chat, 'title', chat.username or str(chat.id))
    chat_type = chat.type

    msg = update.message or update.channel_post or update.edited_message or update.edited_channel_post
    if msg:
        sender = msg.from_user
        if sender:
            sender_name = sender.first_name or sender.username or str(sender.id)
        else:
            sender_name = "Unknown"

        text = msg.text or msg.caption
        if text:
            text_preview = text.replace('\n', '\\n')[:100]
            log.info(f"[{chat_type}:{chat_title}] {sender_name}: {text_preview}")

            # Event detection
            event_info = parse_event_info(text)
            if event_info:
                log.info(f"Potential event detected: {event_info}")
                
                # Store in user_data for the callback
                context.user_data['pending_event'] = event_info
                
                import telegram
                keyboard = [
                    [
                        telegram.InlineKeyboardButton("✅ Ja, speichern", callback_data="confirm_event"),
                        telegram.InlineKeyboardButton("❌ Abbrechen", callback_data="cancel_event"),
                    ]
                ]
                reply_markup = telegram.InlineKeyboardMarkup(keyboard)
                
                confirmation_text = (
                    f"📅 <b>Event erkannt!</b>\n\n"
                    f"<b>Name:</b> {event_info['name']}\n"
                    f"<b>Datum:</b> {event_info['beginn']}\n"
                    f"<b>Zeit:</b> {event_info['uhrzeit']}\n"
                    f"<b>PLZ:</b> {event_info['plz'] or '?'}\n\n"
                    f"Soll ich diesen Termin speichern?"
                )
                await msg.reply_text(confirmation_text, reply_markup=reply_markup, parse_mode="HTML")
        else:
            log.debug(f"[{chat_type}:{chat_title}] message has no text/caption")
    else:
        log.info(f"[{chat_type}:{chat_title}] received non-message update: {update.to_dict()}")


async def handle_callback(update: 'telegram.Update', context: 'tgext.ContextTypes.DEFAULT_TYPE') -> None:
    query = update.callback_query
    await query.answer()
    
    if query.data == "confirm_event":
        event_info = context.user_data.pop('pending_event', None)
        if event_info:
            chat_id = str(update.effective_chat.id)
            _save_event(chat_id, event_info)
            await query.edit_message_text(text=f"✅ Termin '{event_info['name']}' am {event_info['beginn']} wurde gespeichert!")
            log.info(f"Saved event: {event_info}")
        else:
            await query.edit_message_text(text="⚠️ Fehler: Termin-Daten nicht gefunden.")
            
    elif query.data == "cancel_event":
        context.user_data.pop('pending_event', None)
        await query.edit_message_text(text="❌ Vorgang abgebrochen.")


def listen_command(args) -> None:
    import telegram
    import telegram.ext as tgext

    # Fetch history first (blocking the start of polling, which is fine for startup)
    try:
        asyncio.run(print_recent_chat_messages())
    except Exception as ex:
        log.error(f"Error during history fetch: {ex}")

    log.info("Starting bot polling...")

    # Build the application
    application = tgext.Application.builder().token(FSTISCH_BOT_TOKEN).build()

    # Add handler to listen to ALL updates
    application.add_handler(tgext.MessageHandler(tgext.filters.ALL, listen_any), group=0)
    
    # Add callback handler for event confirmation
    application.add_handler(tgext.CallbackQueryHandler(handle_callback))

    # Run the bot
    application.run_polling(allowed_updates=telegram.Update.ALL_TYPES)


async def _new_chat(entity_id: str) -> None:
    client = init_telethon_client()
    async with client:
        entity = await _resolve_entity(client, entity_id)
        if not entity:
            log.error(f"Could not resolve entity: {entity_id}")
            return
        
        chat_id = entity.id
        # normalize to telethon/telegram conventions (often negative for chats/channels)
        # However, entity.id from get_entity is usually positive, but peer IDs matter.
        # Let's trust entity.id for now, but handle packing if needed.
        # Actually telethon usually returns the 'real' ID.
        
        # Determine type
        import telethon.types as ttypes

        etype = "unknown"
        if isinstance(entity, ttypes.User):
            etype = "user"
        elif isinstance(entity, ttypes.Chat):
            etype = "group"
        elif isinstance(entity, ttypes.Channel):
            if entity.megagroup:
                etype = "supergroup"
            else:
                etype = "channel"
        
        title = getattr(entity, 'title', None)
        username = getattr(entity, 'username', None)
        first_name = getattr(entity, 'first_name', None)
        last_name = getattr(entity, 'last_name', None)
        
        # Construct record
        record = {
            "id": chat_id,
            "type": etype,
            "title": title,
            "username": username,
            "first_name": first_name,
            "last_name": last_name,
            "date_added": dt.datetime.now(tz=dt.timezone.utc).isoformat(),
            "owner": None,
            "admins": []
        }
        
        # Fetch Admin/Owner Info
        if etype in ("group", "supergroup", "channel"):
            try:
                import telethon.tl.types as ttltypes
                participants = await client.get_participants(entity, filter=ttltypes.ChannelParticipantsAdmins)
                
                admins = []
                for p in participants:
                    name = p.first_name or p.username or str(p.id)
                    info = {"id": p.id, "name": name}
                    if isinstance(p.participant, ttltypes.ChannelParticipantCreator):
                        record["owner"] = info
                    else:
                        admins.append(info)
                record["admins"] = admins
            except Exception as ex:
                log.warning(f"Could not fetch admin info for new chat {chat_id}: {ex}")

        # Save state
        state = _load_state(path=STATE_FILE)
        if "chats" not in state:
            state["chats"] = {}
        
        # Use str(chat_id) as key
        state["chats"][str(chat_id)] = record
        _save_state(state, path=STATE_FILE)
        log.info(f"Saved chat state: {record}")
        
        print(f"Chat resolved: {title or username or chat_id} ({etype})")
        
        # Fetch history
        await print_recent_chat_messages([chat_id])


async def _find_chat(query: str) -> None:
    client = init_telethon_client()
    async with client:
        log.info(f"Searching for chats matching: {query}")
        dialogs = await client.get_dialogs()
        
        matches = []
        q = query.lower()
        for d in dialogs:
            title = d.name or ""
            username = getattr(d.entity, 'username', "") or ""
            if q in title.lower() or q in username.lower():
                matches.append(d)
        
        if not matches:
            print(f"No chats found matching '{query}'")
            return
            
        print(f"Found {len(matches)} matches:")
        print("-" * 80)
        
        import telethon.types as ttypes
        import telethon.tl.types as ttltypes

        for m in matches:
            ent = m.entity
            etype = "unknown"
            if isinstance(ent, ttypes.User):
                etype = "user"
            elif isinstance(ent, ttypes.Chat):
                etype = "group"
            elif isinstance(ent, ttypes.Channel):
                 etype = "supergroup" if ent.megagroup else "channel"
            
            username = getattr(ent, 'username', None)
            identifier = m.name or username or str(ent.id)
            print(f"[{etype.upper()}] {identifier} (ID: {ent.id})")

            # Fetch Admin/Owner Info
            if etype in ("group", "supergroup", "channel"):
                try:
                    admins = await client.get_participants(ent, filter=ttltypes.ChannelParticipantsAdmins)
                    
                    creator_names = []
                    admin_names = []
                    
                    for admin in admins:
                        # participant attribute holds the 'ChannelParticipant...' object
                        p = admin.participant
                        name = admin.first_name or admin.username or str(admin.id)
                        
                        if isinstance(p, ttltypes.ChannelParticipantCreator):
                            creator_names.append(f"{name} ({admin.id})")
                        else:
                            admin_names.append(f"{name} ({admin.id})")
                    
                    if creator_names:
                        print(f"  Owner: {', '.join(creator_names)}")
                    if admin_names:
                        print(f"  Admins: {', '.join(admin_names)}")
                    if not creator_names and not admin_names:
                        print("  (No admin info accessible)")
                except Exception as ex:
                    print(f"  (Could not fetch admin info: {ex})")
            
            print("-" * 40)


async def _find_user(query: str) -> None:
    client = init_telethon_client()
    async with client:
        from telethon.tl.functions.contacts import SearchRequest
        log.info(f"Searching for users matching: {query}")
        result = await client(SearchRequest(q=query, limit=50))
        
        users = result.users
        if not users:
            print(f"No users found matching '{query}'")
            return
            
        print(f"Found {len(users)} matches:")
        print("-" * 80)
        
        for u in users:
            username = u.username or "(no username)"
            name = f"{u.first_name or ''} {u.last_name or ''}".strip() or "(no name)"
            phone = u.phone or "(no phone)"
            web_link = f"https://web.telegram.org/a/#{u.id}"
            print(f"[USER] {name} - @{username}")
            print(f"       Phone: {phone}")
            print(f"       ID   : {u.id}")
            print(f"       Link : {web_link}")
        print("-" * 80)


def find_chat_command(query: str, args) -> None:
    asyncio.run(_find_chat(query))


def find_user_command(query: str, args) -> None:
    asyncio.run(_find_user(query))


def new_chat_command(entity_id: str, args) -> None:
    asyncio.run(_new_chat(entity_id))


def main(argv: list[str] = sys.argv[1:]) -> int:
    subcmd, args = cli.parse_args(argv, doc=__doc__, defaults={})
    
    # Setup logging
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("telethon.network.mtprotosender").setLevel(logging.WARNING)
    logging.getLogger("telethon.crypto.aes").setLevel(logging.WARNING)

    cli.init_logging(args)

    if subcmd == "new-chat":
        entity_id = args.entity
        if not entity_id:
            # Check if user provided positional arg despite usage showing flag
            if argv:
                 entity_id = argv[0]
            else:
                print("Error: --entity is required for new-chat")
                return 1

        new_chat_command(entity_id, args)
        return 0
    elif subcmd == "history":
        history_command(args)
        return 0
    elif subcmd == "listen":
        listen_command(args)
        return 0
    elif subcmd == "find-chat":
        search = args.search
        if not search and argv:
            # Fallback for positional arg if flag not used
            for item in reversed(argv):
                if item != "find-chat" and not item.startswith("-"):
                    search = item
                    break
        
        if not search:
            print("Error: --search is required for find-chat")
            return 1
            
        find_chat_command(search, args)
        return 0
    elif subcmd == "find-user":
        search = args.search
        if not search and argv:
            # Fallback for positional arg if flag not used
            for item in reversed(argv):
                if item != "find-user" and not item.startswith("-"):
                    search = item
                    break
        
        if not search:
            print("Error: --search is required for find-user")
            return 1
            
        find_user_command(search, args)
        return 0
    else:
        print(__doc__)
        return 1


if __name__ == '__main__':
    sys.exit(main())
