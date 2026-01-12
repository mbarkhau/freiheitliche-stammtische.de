#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = [
#   "python-telegram-bot>=22.5",
# ]
# ///
import sys
import os
import json

# Add scripts to path to import telegram_bot
sys.path.append(os.path.join(os.getcwd(), 'scripts'))

from telegram_bot import parse_event_info

def test_parse_event_info():
    test_cases = [
        {
            "name": "Full details",
            "text": """Nächstes Treffen: Libertärer Stammtisch Frankfurt
Datum: 2026-02-05
Uhrzeit: 19:00
PLZ: 60594""",
            "expected": {
                "name": "Libertärer Stammtisch Frankfurt",
                "beginn": "2026-02-05",
                "uhrzeit": "19:00",
                "plz": "60594"
            }
        },
        {
            "name": "English labels",
            "text": """Event: Crypto Meetup Berlin
Date: 12.12.2025
Time: ab 19 Uhr
Location: 10117""",
            "expected": {
                "name": "Crypto Meetup Berlin",
                "beginn": "12.12.2025",
                "uhrzeit": "ab 19 Uhr",
                "plz": "10117"
            }
        },
        {
            "name": "Minimal/Mixed",
            "text": """Stammtisch Meißen
Datum: 2026-01-15
ab 18 Uhr
Ort: 01662""",
            "expected": {
                "name": "Stammtisch Meißen",
                "beginn": "2026-01-15",
                "uhrzeit": "18 Uhr",
                "plz": "01662"
            }
        }
    ]
    
    for case in test_cases:
        result = parse_event_info(case['text'])
        print(f"Testing: {case['name']}")
        print(f"Result: {json.dumps(result, indent=2)}")
        for key, expected_val in case['expected'].items():
            assert result.get(key) == expected_val, f"Key {key} mismatch: expected {expected_val}, got {result.get(key)}"
        print("PASS")

if __name__ == "__main__":
    try:
        test_parse_event_info()
        print("\nAll tests passed!")
    except AssertionError as e:
        print(f"\nTest failed: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\nAn error occurred: {e}")
        sys.exit(1)
