#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = [
#   "pudb", "ipython",
#   "pillow>=11.1.0",
#   "telethon>=1.42.0",
#   "python-telegram-bot>=22.5",
#   "python-dateutil",
#   "google-api-python-client~=2.188.0",
#   "google-auth~=2.38.0",
#   "requests~=2.32.3",
#   "qrcode~=8.2",
#   "geopy~=2.4.1",
# ]
# ///

"""
Telegram Bot v3 for freiheitliche-stammtische.de

Usage:
    telegram_bot_v3.py [options]

Options:
    -h, --help                  Show this help message and exit
    --sheet-id <id>             Google Sheet ID
    -v, --verbose               Enable verbose logging
"""

import os
import re
import sys
import asyncio
import logging
import pathlib as pl
import datetime as dt
import zoneinfo as zi
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from telethon import TelegramClient

from utils import cli
import gsheet_util as gu

log = logging.getLogger('telegram_bot_v3')

TZ_BERLIN = zi.ZoneInfo("Europe/Berlin")

FSTISCH_API_ID = os.environ.get('FSTISCH_API_ID')
FSTISCH_API_HASH = os.environ.get('FSTISCH_API_HASH')
FSTISCH_BOT_TOKEN = os.environ.get('FSTISCH_BOT_TOKEN')
FSTISCH_APP_TITLE = os.environ.get('FSTISCH_APP_TITLE', 'freiheitliche-stammtische-app')


PROD_SHEET = "1-BypxZnsRGFJ8XeuCIFyleF-4OK-ndsUvpaV6_Oi95s"
TEST_SHEET = "15QeC3F4CPHLNjroghRXHDjO8oBC2wmJBPhTLHF_5XOs"


class BotState:
    def __init__(self, sheet_id: str):
        self.sheet = gu.GSheet(sheet_id)
        self.users = {}  # telegram_id -> user_data
        self.last_sync = None

    def sync_users(self):
        log.info("Syncing users from GSheet...")
        rows = self.sheet.read("kontakte")
        new_users = {}
        for row in rows:
            tg_id = row.get("telegram_id")
            if tg_id:
                new_users[str(tg_id)] = row
        self.users = new_users
        self.last_sync = dt.datetime.now(TZ_BERLIN)
        log.info(f"Synced {len(self.users)} users.")

    def is_user_active(self, tg_id: str | int) -> tuple[bool, str | None]:
        tg_id = str(tg_id)
        user = self.users.get(tg_id)
        if not user:
            return False, "Unknown"
        
        # normalized key for "Bot Modus" is "bot_modus"
        modus = user.get("bot_modus", "").lower()
        if modus == "aktiv":
            return True, "Aktiv"
        return False, user.get("bot_modus", "Inaktiv")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    bot_state: BotState = context.bot_data['state']
    
    is_active, status = bot_state.is_user_active(user_id)
    
    if is_active:
        keyboard = [['Bot Info', 'Meine Termine'], ['Termin Erstellen', 'Termin Löschen']]

        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

        await update.message.reply_text(
            "Beep, boop 🤖\n\n"
            "Hallo, ich bin der freiheitliche-stammtische.de Bot!\n"
            "Ich verwalte Termine auf https://freiheitliche-stammtische.de\n\n"
            "Wie kann ich Ihnen helfen?",
            reply_markup=reply_markup
        )
    elif status == "Unknown":
        log.warning(f"Unauthorized access attempt from {user_id} (@{update.effective_user.username})")
        # Ignore unknown users as per requirements? 
        # "First the bot should only react to users with a known telegram id."
        # "if a message is received, ignore it unless there is a kontakt..."
        pass 
    else:
        await update.message.reply_text("Melde dich bei @ManuelB um dein Konto zu aktivieren")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    user_id = str(update.effective_user.id)
    bot_state: BotState = context.bot_data['state']
    
    is_active, status = bot_state.is_user_active(user_id)
    
    if not is_active:
        if status != "Unknown":
            await update.message.reply_text("Melde dich bei @ManuelB um dein Konto zu aktivieren")
        return

    text = update.message.text
    if text == "Bot Info":
        now = dt.datetime.now(TZ_BERLIN)
        msg = (
            "Beep, boop 🤖\n\n"
            "Hallo, ich bin der freiheitliche-stammtische.de Bot!\n"
            "Ich verwalte Termine auf https://freiheitliche-stammtische.de\n"
            f"Aktuelle Zeit: {now.strftime('%d.%m.%Y %H:%M:%S')}"
        )
        await update.message.reply_text(msg)
    elif text == "Meine Termine":
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        await list_my_events(update, context)
    elif text == "Termin Erstellen" or context.user_data.get('state') == 'awaiting_event_info':
        await handle_create_event(update, context)
    elif text == "Termin Löschen" or context.user_data.get('state') == 'awaiting_delete_selection':
        await handle_delete_event(update, context)

    else:
        await update.message.reply_text("Ich habe dich nicht verstanden.\nNutze /start.")


async def list_my_events(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    bot_state: BotState = context.bot_data['state']
    user_data = bot_state.users.get(user_id)
    user_plz_raw = user_data.get("plz", "")
    user_plz = {plz.strip() for plz in user_plz_raw.split(",")}
    
    if not user_plz:
        await update.message.reply_text("In deinem Kontakt-Profil ist keine PLZ hinterlegt.")
        return

    log.info(f"Fetching events for PLZ {user_plz}")
    
    # Send progress indicator immediately
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    status_msg = await update.message.reply_text("🔍 Suche Termine...")

    termine = await asyncio.to_thread(bot_state.sheet.read, "termine")

    # Filter by PLZ. Some PLZ might be strings or ints in GSheet.
    matches = []
    for termin in termine:
        print(termin)
        plz = termin.get('plz')
        if plz and plz in user_plz:
            matches.append(termin)
    
    if not matches:
        await status_msg.edit_text(f"Keine Termine für PLZ {user_plz} gefunden.")
        return

    await status_msg.delete()

    msg = f"Termine für PLZ {user_plz}:\n\n"
    for t in matches:
        date = t.get("beginn", "Unbekannt")
        time = t.get("uhrzeit", "")
        name = t.get("name", "Stammtisch")
        msg += f"📅 {date} {time}\n📍 {name}\n\n"
    
    await update.message.reply_text(msg)


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

    # Name extraction
    lines = [L.strip() for L in text.split('\n') if L.strip()]
    name = "Unbekanntes Event"
    for line in lines:
        if "stammtisch" in line.lower() or "event:" in line.lower() or "treffen:" in line.lower():
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


async def handle_create_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    bot_state: BotState = context.bot_data['state']
    user_data = bot_state.users.get(user_id)
    
    current_state = context.user_data.get('state')
    text = (update.message.text if update.message else "").strip()

    def get_main_keyboard():
        keyboard = [['Bot Info', 'Meine Termine'], ['Termin Erstellen', 'Termin Löschen']]
        return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


    async def reset_flow(msg: str):
        context.user_data['state'] = None
        context.user_data['flow_step'] = None
        context.user_data['new_event'] = None
        context.user_data['prev_event'] = None
        await update.message.reply_text(msg, reply_markup=get_main_keyboard())

    if text == "Abbrechen":
        await reset_flow("Vorgang abgebrochen.")
        return

    if current_state != 'awaiting_event_info':
        # --- Start Flow: Fetch previous event for defaults ---
        context.user_data['state'] = 'awaiting_event_info'
        context.user_data['flow_step'] = 'ask_name'
        context.user_data['new_event'] = {}
        
        # Find the most recent event by this user's PLZ
        user_plz_raw = user_data.get("plz", "")
        user_plz = {plz.strip() for plz in user_plz_raw.split(",") if plz.strip()}
        
        log.info(f"Searching previous events for user {user_id} with PLZ {user_plz}")
        termine = await asyncio.to_thread(bot_state.sheet.read, "termine")
        user_events = []
        for t in termine:
            t_plz = str(t.get('plz', '')).strip()
            if t_plz in user_plz:
                user_events.append(t)
        
        # Sort by date (descending)
        prev_event = None
        if user_events:
            try:
                # 'beginn' is ISO format yyyy-mm-dd
                user_events.sort(key=lambda t: t.get('beginn', ''), reverse=True)
                prev_event = user_events[0]
            except Exception as e:
                log.warning(f"Error sorting previous events: {e}")

        if prev_event:
            context.user_data['prev_event'] = prev_event
            prev_name = prev_event.get('name', 'Stammtisch')
            keyboard = [['Abbrechen', 'Ja']]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
            await update.message.reply_text(
                f'Soll der Stammtisch weiterhin "{prev_name}" heißen?',
                reply_markup=reply_markup
            )
        else:
            context.user_data['prev_event'] = {}
            keyboard = [['Abbrechen']]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            await update.message.reply_text("Wie soll der Stammtisch heißen?", reply_markup=reply_markup)
        return

    flow_step = context.user_data.get('flow_step')
    prev_event = context.user_data.get('prev_event', {})
    new_event = context.user_data.get('new_event', {})

    if flow_step == 'ask_name':
        if text == 'Ja':
            new_event['name'] = prev_event.get('name', 'Stammtisch')
        else:
            new_event['name'] = text
        
        context.user_data['flow_step'] = 'ask_date'
        keyboard = [['Abbrechen']]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        await update.message.reply_text(
            f"Setze Name auf: {new_event['name']}\n\n"
            "An welchem Tag ist der Stammtisch? (z.B. '31.12')",
            reply_markup=reply_markup
        )

    elif flow_step == 'ask_date':
        # Simple parsing for dates like "11.03" or "am 11.03"
        date_match = re.search(r"(\d{1,2})\.(\d{1,2})", text)
        if date_match:
            try:
                day = int(date_match.group(1))
                month = int(date_match.group(2))
                now = dt.datetime.now(TZ_BERLIN)
                year = now.year
                # If date is in the past, assume next year
                if dt.date(year, month, day) < now.date():
                    year += 1
                event_date = dt.date(year, month, day)
                new_event['beginn'] = event_date.isoformat()
                new_event['ende'] = event_date.isoformat()
                
                context.user_data['flow_step'] = 'confirm_date'
                keyboard = [['Abbrechen', 'Ja']]
                reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
                await update.message.reply_text(
                    f"Der {event_date.strftime('%d.%m.%Y')} wurde erkannt. Korrekt?",
                    reply_markup=reply_markup
                )
            except ValueError:
                await update.message.reply_text("Das scheint kein gültiges Datum zu sein. Bitte erneut versuchen (z.B. '31.12').")
        else:
            await update.message.reply_text("Ich konnte das Datum nicht erkennen. Bitte sende es im Format 'TT.MM'.")

    elif flow_step == 'confirm_date':
        if text == 'Ja':
            context.user_data['flow_step'] = 'ask_time'
            prev_time = prev_event.get('uhrzeit', '19:00')
            keyboard = [['Abbrechen', 'Ja']]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
            await update.message.reply_text(
                f"Um welche Uhrzeit ist der Stammtisch? Weiterhin um {prev_time} Uhr?",
                reply_markup=reply_markup
            )
        else:
            context.user_data['flow_step'] = 'ask_date'
            await update.message.reply_text("Bitte gib das Datum erneut ein (z.B. '31.12').")

    elif flow_step == 'ask_time':
        if text == 'Ja':
            new_event['uhrzeit'] = prev_event.get('uhrzeit', '19:00')
        else:
            # Try parsing time
            time_match = re.search(r"(\d{1,2})[:.](\d{2})|\b(\d{1,2})\s*Uhr", text)
            if time_match:
                if time_match.group(1):
                    new_event['uhrzeit'] = f"{int(time_match.group(1)):02d}:{int(time_match.group(2)):02d}"
                else:
                    new_event['uhrzeit'] = f"{int(time_match.group(3)):02d}:00"
            else:
                new_event['uhrzeit'] = "19:00" # fallback

        context.user_data['flow_step'] = 'ask_plz'
        # Default PLZ from prev event or user profile
        prev_plz = prev_event.get('plz') or user_data.get('plz', '').split(',')[0].strip()
        if prev_plz:
            keyboard = [['Abbrechen', 'Ja']]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
            await update.message.reply_text(
                f"Unter welcher PLZ findet das Treffen statt? Weiterhin unter {prev_plz}?",
                reply_markup=reply_markup
            )
        else:
            keyboard = [['Abbrechen']]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            await update.message.reply_text("Unter welcher PLZ findet das Treffen statt?", reply_markup=reply_markup)

    elif flow_step == 'ask_plz':
        if text == 'Ja':
            new_event['plz'] = prev_event.get('plz') or user_data.get('plz', '').split(',')[0].strip()
        else:
            plz_match = re.search(r"\b(\d{5})\b", text)
            if plz_match:
                new_event['plz'] = plz_match.group(1)
            else:
                await update.message.reply_text("Bitte gib eine gültige 5-stellige PLZ an.")
                return

        # --- Metadata Carry-Forward ---
        # If user confirmed same Name and PLZ, copy metadata from previous event
        if prev_event and new_event.get('name') == prev_event.get('name') and new_event.get('plz') == prev_event.get('plz'):
            # Copy all fields except those explicitly handled by the bot flow
            excluded_keys = {'name', 'beginn', 'ende', 'uhrzeit', 'plz', 'kontakt', 'e-mail'}
            for k, v in prev_event.items():
                if k not in excluded_keys and v:
                    new_event[k] = v

        new_event['kontakt'] = user_data.get('name', update.effective_user.full_name)
        new_event['e-mail'] = user_data.get('e-mail', '')

        # --- Final Confirmation Summary ---
        summary = (
            "Erfassten Angaben für den neuen Termin:\n\n"
            f"📍 Name: {new_event['name']}\n"
            f"📅 Datum: {new_event['beginn']}\n"
            f"⏰ Zeit: {new_event['uhrzeit']}\n"
            f"📮 PLZ: {new_event['plz']}\n"
        )
        
        # Display metadata if present
        if new_event.get('orga'): 
            summary += f"🏢 Orga: {new_event['orga']}\n"
        if new_event.get('orga_webseite'): 
            summary += f"🔗 Web: {new_event['orga_webseite']}\n"
        if new_event.get('telegram'): 
            summary += f"📱 Telegram: {new_event['telegram']}\n"

        summary += f"\nAlles so richtig?\n"
        
        context.user_data['flow_step'] = 'confirm_save'
        keyboard = [['Abbrechen', 'Ja']]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
        await update.message.reply_text(summary, reply_markup=reply_markup)

    elif flow_step == 'confirm_save':
        if text != 'Ja':
            await update.message.reply_text("Bitte bestätige mit 'Ja' oder nutze 'Abbrechen'.")
            return

        # --- Final Save ---
        await update.message.reply_text("Speichere in GSheet...")
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        
        try:
            await asyncio.to_thread(bot_state.sheet.append, "termine", [new_event])
            await update.message.reply_text("✅ Termin wurde erfolgreich gespeichert!")
        except Exception as e:
            log.error(f"Error saving event: {e}")
            await update.message.reply_text("❌ Fehler beim Speichern. Bitte versuche es später erneut.")
        
        await reset_flow("Was kann ich sonst für dich tun?")


async def handle_delete_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    bot_state: BotState = context.bot_data['state']
    user_data = bot_state.users.get(user_id)
    
    current_state = context.user_data.get('state')
    text = (update.message.text if update.message else "").strip()

    def get_main_keyboard():
        keyboard = [['Bot Info', 'Meine Termine'], ['Termin Erstellen', 'Termin Löschen']]
        return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    async def reset_flow(msg: str):
        context.user_data['state'] = None
        context.user_data['delete_candidates'] = None
        context.user_data['selected_event_idx'] = None
        await update.message.reply_text(msg, reply_markup=get_main_keyboard())

    if text == "Abbrechen":
        await reset_flow("Vorgang abgebrochen.")
        return

    if current_state != 'awaiting_delete_selection':
        # --- Step 1: Fetch and display candidates ---
        user_plz_raw = user_data.get("plz", "")
        user_plz = {plz.strip() for plz in user_plz_raw.split(",") if plz.strip()}
        
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        termine = await asyncio.to_thread(bot_state.sheet.read, "termine")
        
        candidates = []
        for i, t in enumerate(termine):
            t_plz = str(t.get('plz', '')).strip()
            if t_plz in user_plz:
                # Store the row index (2 for the first data row)
                candidates.append((i + 2, t))
        
        if not candidates:
            await update.message.reply_text("Ich konnte keine Termine für deine PLZ finden.")
            return

        # Sort by date (descending)
        candidates.sort(key=lambda x: x[1].get('beginn', ''), reverse=True)
        top_4 = candidates[:4]
        top_4.reverse()
        
        context.user_data['state'] = 'awaiting_delete_selection'
        context.user_data['delete_candidates'] = top_4
        
        keyboard = [['Abbrechen']]
        for _, t in top_4:
            # Button text: "dd.mm.yyyy HH:MM - PLZ"
            d = t.get('beginn', '?.?.?')
            time = t.get('uhrzeit', '?:?')
            plz = t.get('plz', '?????')
            keyboard.append([f"{d} {time} - {plz}"])
            
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
        await update.message.reply_text(
            "Welchen Termin möchten Sie löschen?",
            reply_markup=reply_markup
        )
        return

    # User has selected an event or is confirming
    candidates = context.user_data.get('delete_candidates', [])
    selected_idx = context.user_data.get('selected_event_idx')

    if selected_idx is None:
        # User is selecting from buttons
        match = None
        for i, (gs_idx, t) in enumerate(candidates):
            d = t.get('beginn', '?.?.?')
            time = t.get('uhrzeit', '?:?')
            plz = t.get('plz', '?????')
            btn_text = f"{d} {time} - {plz}"
            if text == btn_text:
                match = (i, gs_idx, t)
                break
        
        if not match:
            await update.message.reply_text("Bitte wähle einen der Termine über die Buttons aus.")
            return
        
        i, gs_idx, t = match
        context.user_data['selected_event_idx'] = gs_idx
        
        # Confirm deletion
        summary = (
            "Diesen Termin wirklich unwiderruflich löschen?\n\n"
            f"📍 {t.get('name')}\n"
            f"📅 {t.get('beginn')} {t.get('uhrzeit')}\n"
            f"📮 PLZ: {t.get('plz')}\n"
        )
        keyboard = [['Abbrechen', 'Ja']]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
        await update.message.reply_text(summary, reply_markup=reply_markup)
        
    else:
        # User is confirming deletion
        if text == 'Ja':
            gs_idx = selected_idx
            await update.message.reply_text("Lösche in GSheet...")
            await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
            
            try:
                await asyncio.to_thread(bot_state.sheet.delete_row, "termine", gs_idx)
                await update.message.reply_text("✅ Termin wurde gelöscht.")
            except Exception as e:
                log.error(f"Error deleting event: {e}")
                await update.message.reply_text("❌ Fehler beim Löschen. Bitte versuche es später erneut.")
            
            await reset_flow("Was kann ich sonst für dich tun?")
        else:
            await update.message.reply_text("Bitte bestätige mit 'Ja' oder nutze 'Abbrechen'.")





_CLIENT: "telethon.TelegramClient" = None


def init_telethon_client() -> "telethon.TelegramClient":
    global _CLIENT

    if _CLIENT is None:
        import telethon
        _CLIENT = telethon.TelegramClient(FSTISCH_APP_TITLE, FSTISCH_API_ID, FSTISCH_API_HASH)
    return _CLIENT


async def catch_up():
    log.debug(f"FSTISCH_API_ID: {FSTISCH_API_ID}")
    log.debug(f"FSTISCH_API_HASH: {'set' if FSTISCH_API_HASH else 'NOT SET'}")
    log.debug(f"FSTISCH_BOT_TOKEN: {'set' if FSTISCH_BOT_TOKEN else 'NOT SET'}")

    if not all([FSTISCH_API_ID, FSTISCH_API_HASH, FSTISCH_BOT_TOKEN]):
        log.warning("Telethon environment variables missing, skipping catch-up.")
        return

    log.info("Starting Telethon catch-up...")
    client = init_telethon_client()
    async with client:
        await client.start(bot_token=FSTISCH_BOT_TOKEN)
        me = await client.get_me()
        log.info(f"Catch-up client initialized as {me.username}")
        
        # Example: check for recent messages (simplified)
        async for dialog in client.iter_dialogs(limit=10):
            if dialog.unread_count > 0:
                log.info(f"Unread messages in {dialog.name}: {dialog.unread_count}")


def main():
    _cli_defaults = {"--sheet-id": TEST_SHEET}
    subcmd, args = cli.parse_args(sys.argv[1:], doc=__doc__, defaults=_cli_defaults)
    cli.init_logging(args)

    # Setup logging
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("telethon.network.mtprotosender").setLevel(logging.WARNING)
    logging.getLogger("telethon.crypto.aes").setLevel(logging.WARNING)

    if not FSTISCH_BOT_TOKEN:
        log.error("FSTISCH_BOT_TOKEN not set!")
        sys.exit(1)

    state = BotState(args.sheet_id)
    state.sync_users()

    # Initial catch-up
    asyncio.run(catch_up())

    application = ApplicationBuilder().token(FSTISCH_BOT_TOKEN).build()
    application.bot_data['state'] = state

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))

    log.info("Bot is starting...")
    application.run_polling()

if __name__ == "__main__":
    main()
