#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = [
#   "pudb", "ipython",
#   "pillow>=11.1.0",
#   "qrcode",
# ]
# ///
"""
Generate social media image for the upcoming Stammtisch events.

Options:
    --kw <weeknum>    Generate image for calendar week number (e.g. 12).
                      Assumes a date in the future.
    --help            Show this help message and exit.
"""

import sys
import json
import textwrap
import datetime as dt
import pathlib as pl

from lib.cli import parse_args

from PIL import Image, ImageDraw, ImageFont, ImageFilter

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


def get_next_week_start():
    today = dt.date.today()
    days_to_sunday = 6 - today.weekday()
    return today + dt.timedelta(days=days_to_sunday)


def filter_events(events, start_date) -> list[dict]:
    filtered = []
    for event in events:
        try:
            date = dt.datetime.strptime(event["date"], "%Y-%m-%d").date()
        except (ValueError, KeyError):
            continue
        if start_date <= date:
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


def generate_image(events, start_date) -> pl.Path:
    bg_path = OUTPUT_DIR / "events_bg.png"
    if bg_path.exists():
        img = Image.open(bg_path).convert("RGB")
        if img.size != (WIDTH, HEIGHT):
            img = img.resize((WIDTH, HEIGHT), Image.Resampling.LANCZOS)
    else:
        img = Image.new("RGB", (WIDTH, HEIGHT), BG_COLOR)

    draw = ImageDraw.Draw(img)
    
    # Load fonts
    headline_font = ImageFont.truetype("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf", 50)
    kw_font = ImageFont.truetype("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf", 60)
    date_font = ImageFont.truetype("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf", 50)
    text_font = ImageFont.truetype("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf", 50)
    footer_font = ImageFont.truetype("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf", 42)
    small_font = ImageFont.truetype("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf", 28)

    # Add timeframe top right
    kw_monday = start_date + dt.timedelta(days=1)
    kw_year, kw_num, _ = kw_monday.isocalendar()
    # draw.text(text="STAMMTISCH\nTERMINE", xy=(WIDTH - 60, 60), spacing=6, font=headline_font, fill=TEXT_COLOR, anchor="ra", align="right")
    # draw.text(text=f"KW{kw_num:02d}\n{kw_year}", xy=(60, 60), font=kw_font, fill=TEXT_COLOR, anchor="la", align="left")
    draw.text(text=f"KW{kw_num:02d}\n{kw_year}", xy=(WIDTH - 80, 80), font=kw_font, fill=(200, 200, 200), anchor="ra", align="right")

    # Events offset
    y_offset = 120
    row_height = 80
    max_events = 8
    
    # Center events area
    x_margin = 380

    shadow_layer = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow_layer)
    text_layer = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    text_draw = ImageDraw.Draw(text_layer)

    def draw_shadowed_text(text, xy, shadow_offset=2, **kwargs):
        text_draw.text(text=text, xy=xy, **kwargs)
        kwargs.pop("fill")

        shadow_draw.text(text=text, xy=(xy[0] - shadow_offset, xy[1] - shadow_offset), fill=(0, 0, 0, 255), **kwargs)
        shadow_draw.text(text=text, xy=(xy[0] + shadow_offset, xy[1] - shadow_offset), fill=(0, 0, 0, 255), **kwargs)
        shadow_draw.text(text=text, xy=(xy[0] - shadow_offset, xy[1] + shadow_offset), fill=(0, 0, 0, 255), **kwargs)
        shadow_draw.text(text=text, xy=(xy[0] + shadow_offset, xy[1] + shadow_offset), fill=(0, 0, 0, 255), **kwargs)
    
    prev_city = None
    prev_display_date = None

    for event in events:
        # Date and Day (Left aligned)
        date = dt.datetime.strptime(event["date"], "%Y-%m-%d")
        day_name = date.strftime("%A")
        short_day = DAY_MAP[day_name] + "."
        month_name = date.strftime("%B")
        short_month = MONTH_MAP[month_name]
        
        day_str = date.strftime("%d")
        display_date = f"{short_day} {day_str}. {short_month}"

        if display_date == prev_display_date:
            if prev_city == event["city"]:
                continue
            y_offset -= 20
        else:
            draw_shadowed_text(text=display_date, xy=(x_margin, y_offset + 25), font=date_font, letter_spacing=-2, fill=ACCENT_COLOR, anchor="rm")

        prev_display_date = display_date
        prev_city = event["city"]
        
        max_chars = 20
        wrapped_city = textwrap.wrap(event["city"], width=max_chars)
        
        for line in wrapped_city:
            draw_shadowed_text(text=line, xy=(x_margin + 50, y_offset - 5), font=text_font, fill=TEXT_COLOR)
            y_offset += 50
        
        y_offset += 30

        if y_offset > HEIGHT - 250:
            break
        
    shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(radius=8))
    img.paste(shadow_layer, (0, 0), shadow_layer)
    img.paste(text_layer, (0, 0), text_layer)


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

    output_path = OUTPUT_DIR / f"social_events_{kw_year}_KW{kw_num:02d}.png"
    img.save(output_path)
    return output_path

def main():
    _, args = parse_args(sys.argv[1:], __doc__)

    if not DATA_PATH.exists():
        print(f"Error: {DATA_PATH} not found.")
        return

    with DATA_PATH.open(mode="r") as fobj:
        events = json.load(fobj)

    if args.kw:
        target_kw = int(args.kw)
        today = dt.date.today()
        current_year = today.year
        current_kw = today.isocalendar()[1]

        # If the requested kw is less than the current kw, we assume it's for the next year
        if target_kw < current_kw:
            target_year = current_year + 1
        else:
            target_year = current_year

        # Get the Monday of the target week, then subtract 1 day to get the preceding Sunday
        start_date = dt.date.fromisocalendar(target_year, target_kw, 1) - dt.timedelta(days=1)
    else:
        start_date = get_next_week_start()

    filtered = filter_events(events, start_date)

    if not filtered:
        print(f"No events found for week starting {start_date.strftime('%Y-%m-%d')}")
        return

    output_file = generate_image(filtered, start_date)
    print(f"Successfully generated image: {output_file}")

if __name__ == "__main__":
    main()
