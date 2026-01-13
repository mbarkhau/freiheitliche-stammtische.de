#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = [
#   "pudb", "ipython",
#   "pillow>=11.1.0",
#   "qrcode",
# ]
# ///

import json
import textwrap
import datetime as dt
import pathlib as pl

from PIL import Image, ImageDraw, ImageFont

# Configuration
WIDTH, HEIGHT = 1080, 1080
BG_COLOR = (12, 12, 12)  # Deeper dark theme
TEXT_COLOR = (245, 245, 245)
ACCENT_COLOR = (255, 215, 0)  # Gold/Yellow accent
SECONDARY_TEXT_COLOR = (160, 160, 160)
URL = "https://freiheitliche-stammtische.de"

DATA_PATH = pl.Path("www/termine.json")
OUTPUT_DIR = pl.Path("social_images")
OUTPUT_DIR.mkdir(exist_ok=True)


def get_next_month():
    today = dt.date.today()
    if today.month == 12:
        return dt.date(today.year + 1, 1, 1)
    else:
        return dt.date(today.year, today.month + 1, 1)


def filter_events(events, target_month) -> list[dict]:
    filtered = []
    for event in events:
        try:
            date = dt.datetime.strptime(event["date"], "%Y-%m-%d")
        except (ValueError, KeyError):
            continue
        if date.year == target_month.year and date.month == target_month.month:
            filtered.append(event)

    filtered.sort(key=lambda x: x["date"])
    return filtered


def draw_text(draw, text: str, letter_spacing: int = 0, **kwargs) -> None:
    x, y = kwargs.pop("xy")
    font = kwargs.pop("font")
    for char in text:
        draw.text(text=char, xy=(x, y), font=font, **kwargs)
        left, top, right, bottom = font.getbbox(char)
        char_width = right - left
        x += char_width + letter_spacing


DAY_MAP = {
    "Monday"   : "Mo",
    "Tuesday"  : "Di",
    "Wednesday": "Mi",
    "Thursday" : "Do",
    "Friday"   : "Fr",
    "Saturday" : "Sa",
    "Sunday"   : "So",
}

MONTH_MAP = {
    "January"  : "Jan",
    "February" : "Feb",
    "March"    : "März",
    "April"    : "April",
    "May"      : "Mai",
    "June"     : "Juni",
    "July"     : "Juli",
    "August"   : "Aug",
    "September": "Sept",
    "October"  : "Okt",
    "November" : "Nov",
    "December" : "Dez",
}


def generate_image(events, target_month) -> None:
    bg_path = OUTPUT_DIR / "events_bg.png"
    if bg_path.exists():
        img = Image.open(bg_path).convert("RGB")
        if img.size != (WIDTH, HEIGHT):
            img = img.resize((WIDTH, HEIGHT), Image.Resampling.LANCZOS)
    else:
        img = Image.new("RGB", (WIDTH, HEIGHT), BG_COLOR)

    draw = ImageDraw.Draw(img)
    
    # Load fonts
    date_font = ImageFont.truetype("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf", 45)
    text_font = ImageFont.truetype("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf", 56)
    footer_font = ImageFont.truetype("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf", 42)
    small_font = ImageFont.truetype("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf", 28)

    # Events offset
    y_offset = 320
    row_height = 110
    max_events = 8
    
    # Center events area
    x_margin = 320
    prev_display_date = None
    
    for i, event in enumerate(events[:max_events]):
        # Date and Day (Left aligned)
        date = dt.datetime.strptime(event["date"], "%Y-%m-%d")
        day_name = date.strftime("%A")
        short_day = DAY_MAP[day_name] + "."
        month_name = date.strftime("%B")
        short_month = MONTH_MAP[month_name]
        
        day_str = date.strftime("%d")
        display_date = f"{short_day} {day_str} {short_month}"
        if display_date == prev_display_date:
            y_offset -= 20
        else:
            draw.text(text=display_date, xy=(x_margin, y_offset + 25), font=date_font, letter_spacing=-2, fill=ACCENT_COLOR, anchor="rm")
            prev_display_date = display_date
        
        max_chars = 20
        wrapped_city = textwrap.wrap(event["city"], width=max_chars)
        
        for line in wrapped_city:
            draw.text(text=line, xy=(x_margin + 50, y_offset - 5), font=text_font, fill=TEXT_COLOR)
            y_offset += 50
        
        y_offset += 45
        
    if len(events) > max_events:
        text = f"... und {len(events) - max_events} weitere Termine online"
        draw.text(text=text, xy=(WIDTH//2, y_offset + 20), font=small_font, fill=SECONDARY_TEXT_COLOR, anchor="mm")


    # QR Code
    # import qrcode
    # qr = qrcode.QRCode(version=1, box_size=4, border=2)
    # qr.add_data(URL)
    # qr.make(fit=True)
    # qr_img = qr.make_image(fill_color="white", back_color="black").convert('RGB')

    # Make QR slightly accent-tinted or just white on dark
    # qr_img = qr_img.resize((240, 240))
    # img.paste(qr_img, (WIDTH - 290, HEIGHT - 290))

    # footer_text = "freiheitliche-stammtische.de"
    # draw_text(draw, text=footer_text, xy=(x_margin, HEIGHT - 150), font=footer_font, fill=ACCENT_COLOR)
    # draw_text(draw, text="Alle Libertären Treffen auf einen Blick", xy=(x_margin, HEIGHT - 90), font=small_font, fill=SECONDARY_TEXT_COLOR)

    output_path = OUTPUT_DIR / f"social_events_{target_month.strftime('%Y-%m')}.png"
    img.save(output_path)
    return output_path

def main():
    if not DATA_PATH.exists():
        print(f"Error: {DATA_PATH} not found.")
        return

    with DATA_PATH.open(mode="r") as fobj:
        events = json.load(fobj)

    target_month = get_next_month()
    filtered = filter_events(events, target_month)

    if not filtered:
        print(f"No events found for {target_month.strftime('%Y-%m')}")
        target_month = dt.date.today().replace(day=1)
        filtered = filter_events(events, target_month)
        if not filtered:
             print("No events found for current month either.")
             return

    output_file = generate_image(filtered, target_month)
    print(f"Successfully generated image: {output_file}")

if __name__ == "__main__":
    main()
