# /// script
# requires-python = ">=3.13"
# dependencies = [
#   "python-telegram-bot>=22.5",
#   "python-dateutil",
#   "telethon>=1.42.0",
#   "pillow>=11.1.0",
#   "pudb", "ipython",
# ]
# ///
import sys
import os
import unittest

# Set dummy env vars to bypass assertions in telegram_bot
os.environ['FSTISCH_API_ID'] = '12345'
os.environ['FSTISCH_API_HASH'] = 'dummy_hash'
os.environ['FSTISCH_BOT_TOKEN'] = 'dummy_token'

# Adjust path to import telegram_bot
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from telegram_bot import extract_event_info

class TestEventParsing(unittest.TestCase):
    def test_full_date_time(self):
        text = "Stammtisch am 25.01.2026 um 19:30"
        info = extract_event_info(text)
        self.assertIsNotNone(info)
        self.assertEqual(info['date'], "2026-01-25")
        self.assertEqual(info['time'], "19:30")

    def test_short_date_default_time(self):
        text = "Wir treffen uns am 15.03."
        info = extract_event_info(text)
        self.assertIsNotNone(info)
        # Year depends on current date, assumes current or next year
        # validation logic handles year adjustment, let's just check month/day
        self.assertTrue(info['date'].endswith("-03-15"))
        self.assertEqual(info['time'], "19:00") # Default

    def test_no_date(self):
        text = "Hallo wie gehts?"
        info = extract_event_info(text)
        self.assertIsNone(info)

    def test_explicit_year(self):
        text = "Event am 1.1.25"
        info = extract_event_info(text)
        self.assertIsNotNone(info)
        self.assertEqual(info['date'], "2025-01-01")

if __name__ == '__main__':
    unittest.main()
