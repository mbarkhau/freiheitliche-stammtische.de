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
import qrcode

# Configuration
WIDTH, HEIGHT = 1080, 1080
BG_COLOR = (12, 12, 12)  # Deeper dark theme
TEXT_COLOR = (245, 245, 245)
ACCENT_COLOR = (255, 215, 0)  # Gold/Yellow accent
SECONDARY_TEXT_COLOR = (160, 160, 160)
URL = "https://freiheitliche-stammtische.de"

DATA_PATH = pl.Path("data/termine.json")
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
            beginn = dt.datetime.strptime(event["beginn"], "%Y-%m-%d")
        except (ValueError, KeyError):
            continue
        if beginn.year == target_month.year and beginn.month == target_month.month:
            filtered.append(event)

    filtered.sort(key=lambda x: x["beginn"])
    return filtered


def draw_gradient(draw, width, height, start_color, end_color):
    for i in range(height):
        # Calculate intermediate color
        r = int(start_color[0] + (end_color[0] - start_color[0]) * (i / height))
        g = int(start_color[1] + (end_color[1] - start_color[1]) * (i / height))
        b = int(start_color[2] + (end_color[2] - start_color[2]) * (i / height))
        draw.line([(0, i), (width, i)], fill=(r, g, b))

def draw_text(font, text):
    pass


DAY_MAP = {
    "Monday": "Mo.",
    "Tuesday": "Di.",
    "Wednesday": "Mi.",
    "Thursday": "Do.",
    "Friday": "Fr.",
    "Saturday": "Sa.",
    "Sunday": "So.",
}

MONTH_MAP = {
    "January": "Januar",
    "February": "Februar",
    "March": "März",
    "April": "April",
    "May": "Mai",
    "June": "Juni",
    "July": "Juli",
    "August": "August",
    "September": "September",
    "October": "Oktober",
    "November": "November",
    "December": "Dezember"
}


def generate_image(events, target_month):
    img = Image.new("RGB", (WIDTH, HEIGHT), BG_COLOR)
    draw = ImageDraw.Draw(img)
    
    # Background gradient
    draw_gradient(draw, WIDTH, HEIGHT, (28, 28, 28), (8, 8, 8))
    
    # Load fonts
    try:
        title_font = ImageFont.truetype("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf", 64)
        date_font = ImageFont.truetype("/usr/share/fonts/truetype/liberation/LiberationMono-Bold.ttf", 48)
        text_font = ImageFont.truetype("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf", 36)
        small_font = ImageFont.truetype("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf", 28)
    except Exception:
        title_font = ImageFont.load_default()
        date_font = ImageFont.load_default()
        text_font = ImageFont.load_default()
        small_font = ImageFont.load_default()

    en_month = target_month.strftime("%B")
    de_month = MONTH_MAP[en_month]
    title_text = f"Treffen im {de_month} {target_month.year}"
    
    text_xy = (WIDTH//2, 100)
    draw.text(text=title_text, xy=text_xy, font=title_font, fill=ACCENT_COLOR, anchor="mm")
    
    # Elegant double line under title
    draw.line([(100, 150), (WIDTH - 100, 150)], fill=ACCENT_COLOR, width=4)
    draw.line([(150, 162), (WIDTH - 150, 162)], fill=ACCENT_COLOR, width=1)

    # Events offset
    y_offset = 220
    row_height = 110
    max_events = 8
    
    # Center events area
    x_margin = 120
    
    for i, event in enumerate(events[:max_events]):
        # Date and Day (Left aligned)
        beginn = dt.datetime.strptime(event["beginn"], "%Y-%m-%d")
        day_name = beginn.strftime("%A")
        short_day = DAY_MAP[day_name] + "."
        
        date_str = beginn.strftime("%d.%m")
        display_date = f"{short_day} {date_str}"
        draw.text(text=display_date, xy=(x_margin, y_offset + 5), font=date_font, fill=ACCENT_COLOR)
        
        # Event Name (Offset to the right)
        name_x = x_margin + 340
        
        max_chars = 32
        wrapped_name = textwrap.wrap(event["name"], width=max_chars)
        
        line_y = y_offset + 10
        for line in wrapped_name:
            draw.text(text=line, xy=(name_x, line_y), font=text_font, fill=TEXT_COLOR)
            line_y += 42
        
        # Update row height based on number of lines
        y_offset += max(row_height, (len(wrapped_name) * 42) + 20)
        
    if len(events) > max_events:
        draw.text(text=f"... und {len(events) - max_events} weitere Termine online", xy=(WIDTH//2, y_offset + 20), font=small_font, fill=SECONDARY_TEXT_COLOR, anchor="mm")

    # Bottom Branding and QR Code
    footer_y = HEIGHT - 100
    
    # QR Code
    qr = qrcode.QRCode(version=1, box_size=4, border=2)
    qr.add_data(URL)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="white", back_color="black").convert('RGB')
    # Make QR slightly accent-tinted or just white on dark
    qr_img = qr_img.resize((240, 240))
    img.paste(qr_img, (WIDTH - 290, HEIGHT - 290))

    footer_text = "freiheitliche-stammtische.de"
    draw.text((x_margin, HEIGHT - 110), footer_text, font=text_font, fill=ACCENT_COLOR)
    draw.text((x_margin, HEIGHT - 70), "Alle Libertären Treffen auf einen Blick", font=small_font, fill=SECONDARY_TEXT_COLOR)

    output_path = OUTPUT_DIR / f"social_events_{target_month.strftime('%Y-%m')}.png"
    img.save(output_path)
    return output_path

def main():
    if not DATA_PATH.exists():
        print(f"Error: {DATA_PATH} not found.")
        return

    with open(DATA_PATH, "r") as f:
        events = json.load(f)

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
