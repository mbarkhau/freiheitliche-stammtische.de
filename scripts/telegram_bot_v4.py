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
import typing as typ
import pathlib as pl
import datetime as dt
import zoneinfo as zi
import importlib
import contextlib

from lib import cli
import gsheet_util as gu

import telegram as tg
import telegram.ext as tg_ext


log = logging.getLogger('telegram_bot_v4')

TZ_BERLIN = zi.ZoneInfo("Europe/Berlin")

FSTISCH_API_ID = os.environ.get('FSTISCH_API_ID')
FSTISCH_API_HASH = os.environ.get('FSTISCH_API_HASH')
FSTISCH_BOT_TOKEN = os.environ.get('FSTISCH_BOT_TOKEN')
FSTISCH_APP_TITLE = os.environ.get('FSTISCH_APP_TITLE', 'freiheitliche-stammtische-app')

FSTISCH_BOT_TOKEN = os.environ.get('FSTISCH_TEST_BOT_TOKEN')


PROD_SHEET = "1-BypxZnsRGFJ8XeuCIFyleF-4OK-ndsUvpaV6_Oi95s"
TEST_SHEET = "15QeC3F4CPHLNjroghRXHDjO8oBC2wmJBPhTLHF_5XOs"

ADMIN_IDS = {
    "601316285",    # Manuel
    "1473328156",   # Lukas
}


User = dict[str, str]


def get_user(ctx, tg_id: str) -> User | None:
    sheet = gu.GSheet(ctx['sheet_id'])

    for row in sheet.read("kontakte"):
        if row.get("telegram_id") == tg_id:
            return row

    return None



class BotState:
    def __init__(self, sheet_id: str):
        self.sheet = gu.GSheet(sheet_id)
        self.users = {}  # telegram_id -> user_data
        self.last_sync = None
        self.start_time = dt.datetime.now(TZ_BERLIN)

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
        if tg_id in ADMIN_IDS:
            return True, "Aktiv"

        user = self.users.get(tg_id)
        if not user:
            return False, "Unknown"
        
        # normalized key for "Bot Modus" is "bot_modus"
        modus = user.get("bot_modus", "").lower()
        if modus == "aktiv":
            return True, "Aktiv"
        return False, user.get("bot_modus", "Inaktiv")


async def announce_event(bot, event: dict):
    tg_target = event.get('telegram_group_id')
    if not tg_target:
        tg_target = "-1003804237556"
        log.info(f"No telegram target found in event data. Using fallback: {tg_target}")

    # Clean up target (basic handling)
    tg_target = tg_target.strip()
    if "/" in tg_target: # Handle full URLs
         tg_target = tg_target.split("/")[-1]
    
    # If target looks like an ID (digits, optionally starting with -), convert to int
    if tg_target.lstrip('-').isdigit():
        try:
             tg_target = int(tg_target)
        except ValueError:
             pass

    log.info(f"Attempting to announce event to Telegram group: {tg_target}")

    try:
        # Construct message
        name = event.get('name', 'Stammtisch')
        date_str = event.get('beginn', 'Unbekannt')
        time = event.get('uhrzeit', '19:00')
        plz = event.get('plz', '')
        
        wd = gu.get_weekday_de(date_str)
        try:
           d = dt.date.fromisoformat(date_str)
           date_display = d.strftime("%d.%m.%Y")
        except:
           date_display = date_str

        msg = (
            f"📢 <b>Neuer Termin: {name}</b>\n\n"
            f"📅 {wd} {date_display}\n"
            f"⏰ {time} Uhr\n"
            f"📍 {plz}"
        )

        # Try invalidating cache or different ID formats if "Chat not found"
        chat_id_candidates = [tg_target]
        if isinstance(tg_target, int) and tg_target > 0:
            # Maybe it's a supergroup without the -100 prefix
            chat_id_candidates.append(int(f"-100{tg_target}"))
            # Maybe it's a basic group (negative ID)
            chat_id_candidates.append(-tg_target)
        
        sent_msg = None
        used_chat_id = None
        
        for cid in chat_id_candidates:
            try:
                sent_msg = await bot.send_message(chat_id=cid, text=msg, parse_mode='HTML')
                used_chat_id = cid
                log.info(f"Announcement sent to {cid} (target: {tg_target}), message ID: {sent_msg.message_id}")
                break
            except Exception as e:
                log.warning(f"Failed to send to {cid}: {e}")
                # Check for "Group migrated to supergroup. New chat id: <id>"
                migration_match = re.search(r"New chat id: (-?\d+)", str(e))
                if migration_match:
                    new_chat_id = int(migration_match.group(1))
                    log.info(f"Detected group migration. Retrying with new chat id: {new_chat_id}")
                    try:
                        sent_msg = await bot.send_message(chat_id=new_chat_id, text=msg, parse_mode='HTML')
                        used_chat_id = new_chat_id
                        log.info(f"Announcement sent to {new_chat_id} (target: {tg_target}), message ID: {sent_msg.message_id}")
                        break
                    except Exception as e2:
                        log.warning(f"Failed to send to migrated chat {new_chat_id}: {e2}")
        
        if not sent_msg:
             log.error(f"Could not send announcement to {tg_target} (tried: {chat_id_candidates})")
             return

        # Update tg_target to the working one for pinning/polling
        tg_target = used_chat_id
        
        # Pin the message
        try:
            await bot.pin_chat_message(chat_id=tg_target, message_id=sent_msg.message_id, disable_notification=False)
            log.info(f"Announcement pinned in {tg_target}")
        except Exception as pin_ex:
            log.warning(f"Could not pin message in {tg_target}: {pin_ex}")

        # Send Poll
        try:
            options = ["Ja", "Ja + 1", "Vielleicht", "Zeige Ergebnis"]
            await bot.send_poll(
                chat_id=tg_target,
                question="Wer ist dabei?",
                options=options,
                is_anonymous=False,
                allows_multiple_answers=False,
                type='regular'
            )
            log.info(f"Poll sent to {tg_target}")
            
        except Exception as poll_ex:
            log.error(f"Could not send poll to {tg_target}: {poll_ex}")

    except Exception as e:
        log.error(f"Error executing announcement: {e}")


WELCOME_MESSAGE = (
    "Beep, boop 🤖\n\n"
    "Hallo, ich bin der freiheitliche-stammtische.de Bot!\n"
    "Ich verwalte Termine auf https://freiheitliche-stammtische.de\n\n"
)


async def handle_message(update: tg.Update, context: tg_ext.ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    # Ignore messages that are not DMs
    if update.effective_chat.type != 'private':
        return

    user_id = str(update.effective_user.id)
    bot_state: BotState = context.bot_data['state']
    
    is_active, status = bot_state.is_user_active(user_id)
    
    if not is_active:
        if status != "Unknown":
            await update.message.reply_text("Melde dich bei @ManuelB um dein Konto zu aktivieren")
        return

    text = update.message.text
    state = context.user_data.get('state')
    log.info(f"handle_message: user_id={user_id}, state={state}, text='{text}'")

    if text.lower() in ("bot info", "botinfo", "info"):
        now = dt.datetime.now(TZ_BERLIN)
        start_time_str = bot_state.start_time.strftime('%d.%m.%Y %H:%M:%S')
        msg = (
            WELCOME_MESSAGE +
            f"Bot gestartet: {start_time_str}\n"
            f"Aktuelle Zeit: {now.strftime('%d.%m.%Y %H:%M:%S')}"
        )
        await update.message.reply_text(msg)
    elif text.lower() in ("meine termine", "termine"):
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        await list_my_events(update, context)
    elif text in ("Nutzer Aktivieren", "Nutzer Deaktivieren") or str(state).startswith('awaiting_user_'):
        if user_id in ADMIN_IDS:
            await handle_manage_users(update, context)
        else:
            await update.message.reply_text("Diese Funktion ist nur für Administratoren verfügbar.")
    elif text.lower() in ("termin erstellen", "erstellen", "neu") or state == 'awaiting_event_info':
        await handle_create_event(update, context)
    elif text.lower() in ("termin löschen", "löschen") or state == 'awaiting_delete_selection':
        await handle_delete_event(update, context)
    else:
        await update.message.reply_text("Ich habe dich nicht verstanden.\nNutze /start.")


async def list_my_events(update: tg.Update, context: tg_ext.ContextTypes.DEFAULT_TYPE):
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
        plz = termin.get('plz')
        if plz and plz in user_plz:
            matches.append(termin)
    
    if not matches:
        await status_msg.edit_text(f"Keine Termine für PLZ {user_plz} gefunden.")
        return

    await status_msg.delete()

    msg = f"Termine für PLZ {user_plz}:\n\n"
    for t in matches:
        date_str = t.get("beginn", "Unbekannt")
        time = t.get("uhrzeit", "")
        name = t.get("name", "Stammtisch")
        wd = gu.get_weekday_de(date_str)
        
        # Format date for display
        date_display = date_str
        if date_str != "Unbekannt":
            try:
                d = dt.date.fromisoformat(date_str)
                date_display = d.strftime("%d.%m.%Y")
            except: pass

        msg += f"📅 {wd} {date_display} {time}\n📍 {name}\n\n"
    
    await update.message.reply_text(msg)


def get_main_keyboard(user_id: str):
    keyboard = [['Bot Info', 'Meine Termine'], ['Termin Erstellen', 'Termin Löschen']]
    if user_id in ADMIN_IDS:
        keyboard.append(['Nutzer Aktivieren', 'Nutzer Deaktivieren'])

    return tg.ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


async def handle_create_event(update: tg.Update, context: tg_ext.ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    bot_state: BotState = context.bot_data['state']
    user_data = bot_state.users.get(user_id)
    
    current_state = context.user_data.get('state')
    text = (update.message.text if update.message else "").strip()

    async def reset_flow(msg: str):
        context.user_data['state'] = None
        context.user_data['flow_step'] = None
        context.user_data['new_event'] = None
        context.user_data['prev_event'] = None
        await update.message.reply_text(msg, reply_markup=get_main_keyboard(user_id))

    if text.lower() == "abbrechen":
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
            reply_markup = tg.ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
            await update.message.reply_text(
                f'Soll der Stammtisch weiterhin "{prev_name}" heißen?',
                reply_markup=reply_markup
            )
        else:
            context.user_data['prev_event'] = {}
            keyboard = [['Abbrechen']]
            reply_markup = tg.ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            await update.message.reply_text("Wie soll der Stammtisch heißen?", reply_markup=reply_markup)
        return

    flow_step = context.user_data.get('flow_step')
    prev_event = context.user_data.get('prev_event', {})
    new_event = context.user_data.get('new_event', {})

    if flow_step == 'ask_name':
        if text.lower() == 'ja':
            new_event['name'] = prev_event.get('name', 'Stammtisch')
        else:
            new_event['name'] = text
        
        context.user_data['flow_step'] = 'ask_date'
        keyboard = [['Abbrechen']]
        reply_markup = tg.ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
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
                reply_markup = tg.ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
                wd = gu.get_weekday_de(event_date.isoformat())
                await update.message.reply_text(
                    f"Der {wd} {event_date.strftime('%d.%m.%Y')} wurde erkannt. Korrekt?",
                    reply_markup=reply_markup
                )
            except ValueError:
                await update.message.reply_text("Das scheint kein gültiges Datum zu sein. Bitte erneut versuchen (z.B. '31.12').")
        else:
            await update.message.reply_text("Ich konnte das Datum nicht erkennen. Bitte sende es im Format 'TT.MM'.")

    elif flow_step == 'confirm_date':
        if text.lower() == 'ja':
            context.user_data['flow_step'] = 'ask_time'
            prev_time = prev_event.get('uhrzeit', '19:00')
            keyboard = [['Abbrechen', 'Ja']]
            reply_markup = tg.ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
            await update.message.reply_text(
                f"Um welche Uhrzeit ist der Stammtisch? Weiterhin um {prev_time} Uhr?",
                reply_markup=reply_markup
            )
        else:
            context.user_data['flow_step'] = 'ask_date'
            await update.message.reply_text("Bitte gib das Datum erneut ein (z.B. '31.12').")

    elif flow_step == 'ask_time':
        if text.lower() == 'ja':
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
            reply_markup = tg.ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
            await update.message.reply_text(
                f"Unter welcher PLZ findet das Treffen statt? Weiterhin unter {prev_plz}?",
                reply_markup=reply_markup
            )
        else:
            keyboard = [['Abbrechen']]
            reply_markup = tg.ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            await update.message.reply_text("Unter welcher PLZ findet das Treffen statt?", reply_markup=reply_markup)

    elif flow_step == 'ask_plz':
        if text.lower() == 'ja':
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
            excluded_keys = {'name', 'beginn', 'ende', 'uhrzeit', 'plz', 'kontakt', 'e-mail', 'kw', 'wochentag'}
            for k, v in prev_event.items():
                if k not in excluded_keys and v:
                    new_event[k] = v

        new_event['kontakt'] = user_data.get('name', update.effective_user.full_name)
        new_event['e-mail'] = user_data.get('e-mail', '')

        # --- Final Confirmation Summary ---
        date_str = new_event['beginn']
        wd = gu.get_weekday_de(date_str)
        try:
            d = dt.date.fromisoformat(date_str)
            date_display = d.strftime("%d.%m.%Y")
        except:
            date_display = date_str

        summary = (
            "Erfassten Angaben für den neuen Termin:\n\n"
            f"📍 Name: {new_event['name']}\n"
            f"📅 Datum: {wd} {date_display}\n"
            f"⏰ Zeit: {new_event['uhrzeit']}\n"
            f"📮 PLZ: {new_event['plz']}\n"
        )
        
        # Display metadata if present
        if new_event.get('orga'): 
            summary += f"🏢 Orga: {new_event['orga']}\n"
        if new_event.get('orga_webseite'): 
            summary += f"🔗 Web: {new_event['orga_webseite']}\n"
        tg_val = new_event.get('telegram_group_id') or new_event.get('telegram')
        if tg_val: 
            summary += f"📱 Telegram: {tg_val}\n"

        summary += f"\nAlles so richtig?\n"
        
        context.user_data['flow_step'] = 'confirm_save'
        keyboard = [['Abbrechen', 'Ja']]
        reply_markup = tg.ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
        await update.message.reply_text(summary, reply_markup=reply_markup)

    elif flow_step == 'confirm_save':
        if text.lower() != 'ja':
            await update.message.reply_text("Bitte bestätige mit 'Ja' oder nutze 'Abbrechen'.")
            return

        # --- Final Save ---
        await update.message.reply_text("Speichere in GSheet...")
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        
        try:
            username = update.effective_user.username or "Unknown"
            bot_state.sheet.log(f"User @{username} ({user_id}) created event: {new_event['name']} on {new_event['beginn']} at {new_event['plz']}")
            await asyncio.to_thread(bot_state.sheet.append, "termine", [new_event])
            
            success_msg = "✅ Termin wurde erfolgreich gespeichert!"
            if bot_state.sheet.sheet_id == PROD_SHEET:
                success_msg += "\nDie Änderungen werden in 1-2 Minuten auf der Webseite sichtbar sein."
                # Run sync and push in the background
                plz = str(new_event.get('plz', ''))

                log.info(f"Starting git sync and push")
                # 1. Sync from GSheet to JSON files
                await asyncio.to_thread(gu.sync_cmd, sheet_id)

                await asyncio.to_thread(
                    util.git_push,
                    bot_state.sheet.sheet_id,
                    message=f"new event for {plz}",
                    repo_paths=["data/termine.json", "www/termine.json", "www/img/"],
                )
                bot_state.sheet.log(f"Git push successful: new event for {plz}")

            asyncio.create_task(announce_event(context.bot, new_event))
            await update.message.reply_text(success_msg)
        except Exception as e:
            log.error(f"Error saving event: {e}")
            await update.message.reply_text("❌ Fehler beim Speichern. Bitte versuche es später erneut.")
        
        await reset_flow("Was kann ich sonst für dich tun?")


async def handle_delete_event(update: tg.Update, context: tg_ext.ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    bot_state: BotState = context.bot_data['state']
    user_data = bot_state.users.get(user_id)
    
    current_state = context.user_data.get('state')
    text = (update.message.text if update.message else "").strip()

    async def reset_flow(msg: str):
        context.user_data['state'] = None
        context.user_data['delete_candidates'] = None
        context.user_data['selected_event_idx'] = None
        await update.message.reply_text(msg, reply_markup=get_main_keyboard(user_id))

    if text.lower() == "abbrechen":
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
            # Button text: "wd dd.mm.yyyy HH:MM - PLZ"
            date_str = t.get('beginn', '?.?.?')
            wd = gu.get_weekday_de(date_str)
            time = t.get('uhrzeit', '?:?')
            plz = t.get('plz', '?????')
            
            date_display = date_str
            try:
                d = dt.date.fromisoformat(date_str)
                date_display = d.strftime("%d.%m.%Y")
            except: pass

            keyboard.append([f"{wd} {date_display} {time} - {plz}"])
            
        reply_markup = tg.ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
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
            date_str = t.get('beginn', '?.?.?')
            wd = gu.get_weekday_de(date_str)
            time = t.get('uhrzeit', '?:?')
            plz = t.get('plz', '?????')
            
            date_display = date_str
            try:
                d = dt.date.fromisoformat(date_str)
                date_display = d.strftime("%d.%m.%Y")
            except: pass

            btn_text = f"{wd} {date_display} {time} - {plz}"
            if text == btn_text:
                match = (i, gs_idx, t)
                break
        
        if not match:
            await update.message.reply_text("Bitte wähle einen der Termine über die Buttons aus.")
            return
        
        i, gs_idx, t = match
        context.user_data['selected_event_idx'] = gs_idx
        
        date_str = t.get('beginn', '?.?.?')
        wd = gu.get_weekday_de(date_str)
        try:
            d = dt.date.fromisoformat(date_str)
            date_display = d.strftime("%d.%m.%Y")
        except:
            date_display = date_str

        # Confirm deletion
        summary = (
            "Diesen Termin wirklich unwiderruflich löschen?\n\n"
            f"📍 {t.get('name')}\n"
            f"📅 {wd} {date_display} {t.get('uhrzeit')}\n"
            f"📮 PLZ: {t.get('plz')}\n"
        )
        keyboard = [['Abbrechen', 'Ja']]
        reply_markup = tg.ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
        await update.message.reply_text(summary, reply_markup=reply_markup)
        
    else:
        # User is confirming deletion
        if text.lower() == 'ja':
            gs_idx = selected_idx
            await update.message.reply_text("Lösche in GSheet...")
            await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
            
            # Find the event data for the commit message before deleting
            target_event = None
            for idx, ev in context.user_data.get('delete_candidates', []):
                if idx == gs_idx:
                    target_event = ev
                    break

            try:
                if target_event:
                    username = update.effective_user.username or "Unknown"
                    bot_state.sheet.log(f"User @{username} ({user_id}) deleted event: {target_event.get('name')} on {target_event.get('beginn')} at {target_event.get('plz')}")
                
                await asyncio.to_thread(bot_state.sheet.delete_row, "termine", gs_idx)
                
                success_msg = "✅ Termin wurde gelöscht."
                if bot_state.sheet.sheet_id == PROD_SHEET:
                    success_msg += "\nDie Änderungen werden in 1-2 Minuten auf der Webseite sichtbar sein."
                    if target_event:
                        plz = str(target_event.get('plz', ''))

                        # 1. Sync from GSheet to JSON files
                        await asyncio.to_thread(gu.sync_cmd, bot_state.sheet.sheet_id)

                        await asyncio.to_thread(
                            util.git_push,
                            bot_state.sheet.sheet_id,
                            message=f"delete event for {plz}",
                            repo_paths=["data/termine.json", "www/termine.json", "www/img/"],
                        )
                        bot_state.sheet.log(f"Git push successful: delete event for {plz}")

                await update.message.reply_text(success_msg)
            except Exception as e:
                log.error(f"Error deleting event: {e}")
                await update.message.reply_text("❌ Fehler beim Löschen. Bitte versuche es später erneut.")
            
            await reset_flow("Was kann ich sonst für dich tun?")
        else:
            await update.message.reply_text("Bitte bestätige mit 'Ja' oder nutze 'Abbrechen'.")


async def handle_manage_users(update: tg.Update, context: tg_ext.ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    bot_state: BotState = context.bot_data['state']
    
    current_state = context.user_data.get('state')
    text = (update.message.text if update.message else "").strip()
    log.info(f"handle_manage_users: state={current_state}, text='{text}'")

    async def reset_flow(msg: str):
        context.user_data['state'] = None
        context.user_data['manage_candidates'] = None
        context.user_data['selected_user_data'] = None
        context.user_data['target_status'] = None
        await update.message.reply_text(msg, reply_markup=get_main_keyboard(user_id))

    if text.lower() == "abbrechen":
        await reset_flow("Vorgang abgebrochen.")
        return

    if text in ("Nutzer Aktivieren", "Nutzer Deaktivieren"):
        # --- Step 1: Fetch and display candidates ---
        target_status = "Aktiv" if text == "Nutzer Aktivieren" else "Deaktiviert"
        context.user_data['target_status'] = target_status
        
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        rows = await asyncio.to_thread(bot_state.sheet.read, "kontakte")
        
        candidates = []
        for i, row in enumerate(rows):
            current_status = row.get("bot_modus", "").strip()
            # If activating, show anyone who isn't already "Aktiv"
            # If deactivating, show anyone who is "Aktiv"
            if text == "Nutzer Aktivieren" and current_status != "Aktiv":
                candidates.append((i + 2, row))
            elif text == "Nutzer Deaktivieren" and current_status == "Aktiv":
                candidates.append((i + 2, row))
        
        if not candidates:
            await update.message.reply_text(f"Keine Nutzer gefunden, die {text.lower()} werden können.")
            return

        context.user_data['state'] = 'awaiting_user_selection'
        context.user_data['manage_candidates'] = candidates
        
        keyboard = [['Abbrechen']]
        for _, row in candidates:
            name = row.get("name", "Unbekannt")
            username = row.get("username", "")
            btn_text = f"{name} (@{username})" if username else name
            keyboard.append([btn_text])
            
        reply_markup = tg.ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
        await update.message.reply_text(
            f"Welchen Nutzer möchten Sie {target_status.lower()}?",
            reply_markup=reply_markup
        )
        return

    if current_state == 'awaiting_user_selection':
        candidates = context.user_data.get('manage_candidates', [])
        target_status = context.user_data.get('target_status')
        
        match = None
        for gs_idx, row in candidates:
            name = row.get("name", "Unbekannt")
            username = row.get("username", "")
            btn_text = f"{name} (@{username})" if username else name
            if text == btn_text:
                match = (gs_idx, row)
                break
        
        if not match:
            await update.message.reply_text("Bitte wählen Sie einen Nutzer über die Buttons aus.")
            return
        
        gs_idx, row = match
        context.user_data['selected_user_data'] = (gs_idx, row)
        context.user_data['state'] = 'awaiting_user_confirm'
        
        summary = (
            f"Möchten Sie diesen Nutzer wirklich {target_status.lower()}?\n\n"
            f"👤 Name: {row.get('name')}\n"
            f"🆔 Telegram ID: {row.get('telegram_id')}\n"
            f"🏷 Username: @{row.get('username', 'N/A')}\n"
        )
        keyboard = [['Abbrechen', 'Ja']]
        reply_markup = tg.ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
        await update.message.reply_text(summary, reply_markup=reply_markup)
        return

    if current_state == 'awaiting_user_confirm':
        if text.lower() != 'ja':
            await update.message.reply_text("Bitte bestätigen Sie mit 'Ja' oder nutzen Sie 'Abbrechen'.")
            return

        gs_idx, row = context.user_data.get('selected_user_data')
        target_status = context.user_data.get('target_status')

        await update.message.reply_text(f"Setze Status auf '{target_status}' in GSheet...")
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

        try:
            # We need to find the column index for "Bot modus"
            headers = await asyncio.to_thread(bot_state.sheet._get_headers, "kontakte")
            col_idx = -1
            for i, h in enumerate(headers):
                if gu._normalize_key(h) == "bot_modus":
                    col_idx = i
                    break

            if col_idx == -1:
                # Append header if missing? Better to fail safely
                await update.message.reply_text("❌ Fehler: Spalte 'Bot modus' nicht gefunden.")
                return

            # Convert col_idx to A, B, C...
            col_letter = chr(ord('A') + col_idx)
            range_name = f"{col_letter}{gs_idx}"

            # Perform update
            body = {"values": [[target_status]]}
            bot_state.sheet.service.spreadsheets().values().update(
                spreadsheetId=bot_state.sheet.sheet_id,
                range=f"kontakte!{range_name}",
                valueInputOption="RAW",
                body=body
            ).execute()

            bot_state.sync_users()

            if target_status == "Aktiv":
                user_tg_id = row.get("telegram_id")
                if user_tg_id:
                    msg = (
                        WELCOME_MESSAGE +
                        "Ihr Konto wurde aktiviert und Sie können jetzt Termine für Ihren Stammtisch verwalten.\n\n" +
                        "Um Befehle zu initiieren, schreibe: /start"
                    )
                    await context.bot.send_message(chat_id=user_tg_id, text=msg)

            admin_username = update.effective_user.username or "Unknown"
            bot_state.sheet.log(f"Admin @{admin_username} ({user_id}) set status of {row.get('telegram_id')} ({row.get('name')}) to {target_status}")
            await update.message.reply_text(f"✅ Nutzer wurde erfolgreich {target_status.lower()}.")
        except Exception as e:
            log.error(f"Error updating user status: {e}")
            await update.message.reply_text("❌ Fehler beim Aktualisieren. Bitte versuche es später erneut.")

        await reset_flow("Was kann ich sonst für dich tun?")


async def handle_start(update: tg.Update, context: tg_ext.ContextTypes.DEFAULT_TYPE) -> None:
    ctx = context.bot_data['ctx']
    tg_id = str(update.effective_user.id)

    await context.bot.send_chat_action(chat_id=tg_id, action="typing")
    user = get_user(ctx, tg_id)

    if user is None:
        # TODO: send notification to admins
        await update.message.reply_text("Melde dich bei @ManuelBTC21 um dein Konto zu aktivieren")
        return

    if user['bot_modus'] != "Aktiv":
        log.warning(f"Unauthorized access attempt from {tg_id} (@{update.effective_user.username})")
        return

    keyboard = [['Bot Info', 'Meine Termine'], ['Termin Erstellen', 'Termin Löschen']]

    if tg_id in ADMIN_IDS:
        keyboard.append(['Nutzer Aktivieren', 'Nutzer Deaktivieren'])

    reply_markup = tg.ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    await update.message.reply_text(
        WELCOME_MESSAGE +
        "Wie kann ich Ihnen helfen?",
        reply_markup=reply_markup
    )


async def handle_attachment(update: tg.Update, context: tg_ext.ContextTypes.DEFAULT_TYPE) -> None:
    ctx = context.bot_data['ctx']
    tg_id = str(update.effective_user.id)
    print(update)


_CHAT_STATE = {}


@contextlib.contextmanager
def chat_state(tg_id: str) -> typ.Generator[dict, None, None]:
    # TODO: load persisted state
    if tg_id not in _CHAT_STATE:
        _CHAT_STATE[tg_id] = {}

    yield _CHAT_STATE[tg_id]
    # TODO: persist, so we can restart the bot


import telegram_bot_v4_handlers


async def dispatch_handler(update: tg.Update, context: tg_ext.ContextTypes.DEFAULT_TYPE) -> None:
    ctx = context.bot_data['ctx']
    tg_id = str(update.effective_user.id)
    user = get_user(ctx, tg_id)

    if user is None:
        # TODO: send notification to admins
        await update.message.reply_text("Melde dich bei @ManuelBTC21 um dein Konto zu aktivieren")
        return

    handlers = importlib.reload(telegram_bot_v4_handlers)

    with chat_state(tg_id):
        print(update)
        await update.message.reply_text(handlers._version)


def main() -> int:
    # _cli_defaults = {"--sheet-id": PROD_SHEET}
    _cli_defaults = {"--sheet-id": TEST_SHEET}
    subcmd, args = cli.parse_args(sys.argv[1:], doc=__doc__, defaults=_cli_defaults)
    cli.init_logging(args)

    # Setup logging
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("telethon.network.mtprotosender").setLevel(logging.WARNING)
    logging.getLogger("telethon.crypto.aes").setLevel(logging.WARNING)

    if not FSTISCH_BOT_TOKEN:
        log.error("FSTISCH_BOT_TOKEN not set!")
        return 1

    sheet_id = PROD_SHEET if args.sheet_id == 'prod' else args.sheet_id

    # state = BotState(sheet_id)
    # state.sync_users()

    app = tg_ext.ApplicationBuilder().token(FSTISCH_BOT_TOKEN).build()
    app.bot_data['ctx'] = {'sheet_id': sheet_id}

    app.add_handler(tg_ext.MessageHandler(tg_ext.filters.TEXT, dispatch_handler))
    app.add_handler(tg_ext.MessageHandler(tg_ext.filters.ATTACHMENT, dispatch_handler))

    log.info("Bot is starting...")
    app.run_polling()


if __name__ == "__main__":
    sys.exit(main())

