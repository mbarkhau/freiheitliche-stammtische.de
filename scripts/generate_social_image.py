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
    --no-cache        Ignore cached images (always regen).
    --kw <weeknum>    Generate image for calendar week number (e.g. 12).
                      Assumes a date in the future.
    --help            Show this help message and exit.
"""

import sys
import json
import shutil
import logging
import textwrap
import pathlib as pl
import hashlib as hl
import datetime as dt
import contextlib

from lib.cli import parse_args

from PIL import Image, ImageDraw, ImageFont, ImageFilter

log = logging.getLogger(name="gsheet_util.py")


# Configuration
WIDTH, HEIGHT = 2160, 2160
LOGO_SIZE = 110
BG_COLOR = (12, 12, 12)  # Deeper dark theme
TEXT_COLOR = (245, 245, 245)
ACCENT_COLOR = (255, 215, 0)  # Gold/Yellow accent
SECONDARY_TEXT_COLOR = (160, 160, 160)
URL = "https://freiheitliche-stammtische.de"

DATA_PATH = pl.Path("www/termine.json")
SOCIAL_IMG_PATH = pl.Path("www/img/social_tile.jpg")
OUTPUT_DIR = pl.Path("social_images")
OUTPUT_DIR.mkdir(exist_ok=True)
MANIFEST_PATH = OUTPUT_DIR / "manifest.json"


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

ORGA_BRANDING = {
    "Unabhängig": ("logo_256.png", "#EEEEEE"),
    "DIE LIBERTÄREN": ("logo_die-libertaeren.png", "#EEEEEE"),
    "Hayek Club": ("logo_hayek-club.png", "#EEEEEE"),
    "Staatenlos": ("logo_staatenlos.png", "#FCC920"),
    "Free Cities Foundation": ("logo_free-cities.png", "#EEEEEE"),
    "Bündnis Libertärer": ("logo_blib.png", "#EEEEEE"),
    "Bündnis Deutschland": ("logo_bd.png", "#EEEEEE"),
    "Milei Institut": ("logo_milei-institut.png", "#d0d0d0"),
    "Partei der Vernunft": ("logo_pdv.png", "#EEEEEE"),
    "Team Freiheit": ("logo_tf.png", "#122E76"),
}

def get_orga_logo(orga: str) -> tuple[str, str]:
    if not orga:
        return "logo_256.png", "#EEEEEE"
    if orga in ORGA_BRANDING:
        return ORGA_BRANDING[orga]
    for key, logo_bg in ORGA_BRANDING.items():
        if key in orga:
            return logo_bg
    return "logo_256.png", "#EEEEEE"

@contextlib.contextmanager
def images_manifest_ctx() -> dict[str, str]:
    manifest_data_in = None
    manifest = {}
    try:
        with MANIFEST_PATH.open(mode="r") as fobj:
            manifest_data_in = fobj.read()
        manifest = json.loads(manifest_data_in)
    except:
        pass

    yield manifest

    manifest_data_out = json.dumps(manifest)
    if manifest_data_out == manifest_data_in:
        return

    manifest_tmp_path = MANIFEST_PATH.parent / "manifest.json.tmp"
    with manifest_tmp_path.open(mode="w") as fobj:
        fobj.write(manifest_data_out)

    manifest_tmp_path.rename(MANIFEST_PATH)


def generate_image(events, start_date, no_cache: bool=False) -> pl.Path:
    kw_monday = start_date + dt.timedelta(days=1)
    kw_year, kw_num, _ = kw_monday.isocalendar()
    output_path = OUTPUT_DIR / f"social_events_{kw_year}_KW{kw_num:02d}.jpg"

    events_json = json.dumps(events, sort_keys=True).encode("utf-8")
    events_hash = hl.sha256(events_json + f"{kw_year}KW{kw_num}".encode("ascii")).hexdigest()

    use_cache = not no_cache
    if use_cache:
        with images_manifest_ctx() as manifest:
            if manifest.get(str(output_path.name)) == events_hash:
                log.info(f"Data unchanged for {output_path.name}")
                return output_path

    bg_path = OUTPUT_DIR / "events_bg.png"
    if bg_path.exists():
        img = Image.open(bg_path).convert("RGB")
        if img.size != (WIDTH, HEIGHT):
            img = img.resize((WIDTH, HEIGHT), Image.Resampling.LANCZOS)
    else:
        img = Image.new("RGB", (WIDTH, HEIGHT), BG_COLOR)

    draw = ImageDraw.Draw(img)
    
    # Load fonts
    headline_font = ImageFont.truetype("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf", 100)
    kw_font = ImageFont.truetype("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf", 120)
    date_font = ImageFont.truetype("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf", 100)
    text_font = ImageFont.truetype("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf", 100)
    footer_font = ImageFont.truetype("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf", 84)
    small_font = ImageFont.truetype("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf", 56)

    # Add timeframe top right
    # draw.text(text="STAMMTISCH\nTERMINE", xy=(WIDTH - 120, 120), spacing=12, font=headline_font, fill=TEXT_COLOR, anchor="ra", align="right")
    # draw.text(text=f"KW{kw_num:02d}\n{kw_year}", xy=(120, 120), font=kw_font, fill=TEXT_COLOR, anchor="la", align="left")
    draw.text(text=f"KW{kw_num:02d}\n{kw_year}", xy=(WIDTH - 160, 160), font=kw_font, fill=(200, 200, 200), anchor="ra", align="right")

    # Events offset
    y_offset = 300
    row_height = 160
    max_events = 8
    
    # Center events area
    x_margin = 700

    shadow_layer = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow_layer)
    text_layer = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    text_draw = ImageDraw.Draw(text_layer)

    def draw_shadowed_text(text, xy, shadow_offset=4, **kwargs):
        text_draw.text(text=text, xy=xy, **kwargs)
        kwargs.pop("fill")

        shadow_draw.text(text=text, xy=(xy[0] - shadow_offset, xy[1] - shadow_offset), fill=(0, 0, 0, 255), **kwargs)
        shadow_draw.text(text=text, xy=(xy[0] + shadow_offset, xy[1] - shadow_offset), fill=(0, 0, 0, 255), **kwargs)
        shadow_draw.text(text=text, xy=(xy[0] - shadow_offset, xy[1] + shadow_offset), fill=(0, 0, 0, 255), **kwargs)
        shadow_draw.text(text=text, xy=(xy[0] + shadow_offset, xy[1] + shadow_offset), fill=(0, 0, 0, 255), **kwargs)
    
    # Group events by (date, city)
    grouped_events = {}
    for event in events:
        date = dt.datetime.strptime(event["date"], "%Y-%m-%d")
        day_name = date.strftime("%A")
        short_day = DAY_MAP[day_name] + "."
        month_name = date.strftime("%B")
        short_month = MONTH_MAP[month_name]
        
        day_str = date.strftime("%d")
        display_date = f"{short_day} {day_str}. {short_month}"

        key = (display_date, event["city"])
        if key not in grouped_events:
            grouped_events[key] = {"date": display_date, "city": event["city"], "orgas": []}
        
        orga = event.get("orga") or "Unabhängig"
        if orga not in grouped_events[key]["orgas"]:
            grouped_events[key]["orgas"].append(orga)

    prev_display_date = None
    prev_logo_path = None
    logo_tasks = []

    for key, group in grouped_events.items():
        display_date = group["date"]
        city = group["city"]
        city = city.replace("Frankfurt am Main", "Frankfurt (FFM)")
        orgas = group["orgas"]

        if display_date == prev_display_date:
            y_offset -= 40
        else:
            xy = (x_margin, y_offset + LOGO_SIZE // 2)
            draw_shadowed_text(text=display_date, xy=xy, font=date_font, letter_spacing=-4, fill=ACCENT_COLOR, anchor="rm")

        prev_display_date = display_date
        logo_x = x_margin + LOGO_SIZE // 2

        for orga in orgas:
            logo_filename, logo_bg = get_orga_logo(orga)
            logo_path = pl.Path("www/img") / logo_filename
            if logo_path.exists():
                if logo_path != prev_logo_path:
                    logo_tasks.append((logo_path, logo_bg, (logo_x, y_offset)))

                prev_logo_path = logo_path
                logo_x += LOGO_SIZE + 16
        
        city_x = max(x_margin + 100, logo_x + 16)
        shift = city_x - (x_margin + 100)
        chars_to_reduce = int(shift / 50)
        max_chars = max(10, 20 - chars_to_reduce)
        
        wrapped_city = textwrap.wrap(city, width=max_chars)
        
        for line in wrapped_city:
            draw_shadowed_text(text=line, xy=(city_x, y_offset - 8), font=text_font, fill=TEXT_COLOR)
            y_offset += 100
        
        y_offset += 60

        if y_offset > HEIGHT - 440:
            break
        
    shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(radius=18))
    img.paste(shadow_layer, (0, 0), shadow_layer)
    img.paste(text_layer, (0, 0), text_layer)
    
    def hex_to_rgb(hex_str: str) -> tuple[int, int, int]:
        hex_str = hex_str.lstrip('#')
        if len(hex_str) == 3:
            hex_str = ''.join(c + c for c in hex_str)
        return tuple(int(hex_str[i:i+2], 16) for i in (0, 2, 4))

    for logo_path, logo_bg, xy in logo_tasks:
        try:
            logo = Image.open(logo_path).convert("RGBA")
            logo.thumbnail((LOGO_SIZE, LOGO_SIZE), Image.Resampling.LANCZOS)
            
            # create mask for rounded rectangle
            mask = Image.new("L", (LOGO_SIZE, LOGO_SIZE), 0)
            mask_draw = ImageDraw.Draw(mask)
            mask_draw.rounded_rectangle((0, 0, LOGO_SIZE, LOGO_SIZE), radius=28, fill=255)
            
            # create background layer
            bg_color = hex_to_rgb(logo_bg)
            bg_layer = Image.new("RGBA", (LOGO_SIZE, LOGO_SIZE), (*bg_color, 255))
            
            # center icon on bg (in case thumbnail is smaller than 44x44)
            logo_x = (LOGO_SIZE - logo.width) // 2
            logo_y = (LOGO_SIZE - logo.height) // 2
            bg_layer.paste(logo, (logo_x, logo_y), logo)
            
            # paste onto main image using rounded mask
            img.paste(bg_layer, xy, mask)
        except Exception as e:
            log.error(f"Failed to load icon {logo_path}: {e}")

    # QR Code
    # import qrcode
    # qr = qrcode.QRCode(version=1, box_size=8, border=4)
    # ...
    # qr_img = qr_img.resize((480, 480))
    # img.paste(qr_img, (WIDTH - 580, HEIGHT - 580))

    # footer_text = "freiheitliche-stammtische.de"
    # draw_text(draw, text=footer_text, xy=(x_margin, HEIGHT - 300), font=footer_font, fill=ACCENT_COLOR)
    # draw_text(draw, text="Alle Libertären Treffen auf einen Blick", xy=(x_margin, HEIGHT - 180), font=small_font, fill=SECONDARY_TEXT_COLOR)

    final_img = img.resize((1080, 1080), Image.Resampling.LANCZOS)
    final_img.save(output_path, quality=90)
    shutil.copy(output_path, SOCIAL_IMG_PATH)

    with images_manifest_ctx() as manifest:
        manifest[str(output_path.name)] = events_hash

    return output_path


def gen_image(start_date: dt.date, no_cache: bool = False):
    with DATA_PATH.open(mode="r") as fobj:
        events = json.load(fobj)

    filtered_events = filter_events(events, start_date)

    if filtered_events:
        generate_image(filtered_events, start_date, no_cache=no_cache)
    else:
        log.warn(f"No events found for week starting {start_date.strftime('%Y-%m-%d')}")



def main():
    _, args = parse_args(sys.argv[1:], __doc__)

    if not DATA_PATH.exists():
        print(f"Error: {DATA_PATH} not found.")
        return

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
    
    gen_image(start_date, no_cache=args.no_cache)

if __name__ == "__main__":
    main()
