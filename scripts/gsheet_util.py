#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = [
#   "pudb", "ipython",
#   "requests",
#   "geopy",
#   "qrcode",
#   "Pillow",
# ]
# ///
"""
Google Sheets → www/*.json downloader.

Works with sheets shared as "Anyone with the link can view".

Usage:
    gsheet_util.py [--sheet-id <sheet_id>] [--sheet-name <sheet_name>]

Options:
    --sheet-id <sheet_id>      Long ID from the Google Sheets URL
    --sheet-name <sheet_name>  Name of the tab (e.g. 'termine')
    -v, --verbose         Enable verbose logging
    -q, --quiet           Enable quiet logging
    -h, --help            Show this help message and exit
"""

import io
import sys
import csv
import time
import json
import logging
import pathlib as pl
import hashlib as hl
import argparse
import typing as typ

import qrcode
import requests
from utils import disk_cache
from utils import cli
from utils.decorators import rate_limit

from geopy.geocoders import get_geocoder_for_service
from geopy.distance import geodesic

from PIL import Image


log = logging.getLogger(name="gsheet_util.py")


EN_DE_WEEKDAYS = {
    "Monday"    : "Mo.",
    "Tuesday"   : "Di.",
    "Wednesday" : "Mi.",
    "Thursday"  : "Do.",
    "Friday"    : "Fr.",
    "Saturday"  : "Sa.",
    "Sunday"    : "So.",
}


Lat = typ.TypeVar("Lat", bound=float)
Lon = typ.TypeVar("Lon", bound=float)

APP_USER_AGENT = "freiheitliche-stammtische.de-plz-resolver-v0.01"

_CITIES_PATH = pl.Path("data/cities.json")
_CITIES_DATA = _CITIES_PATH.open(mode="r", encoding="utf-8").read()
CITIES: list[dict[str, str | int | list[float]]] = json.loads(_CITIES_DATA)


def find_nearest_city(lat: float, lon: float) -> tuple[dict | None, float]:
    nearest_city = None
    nearest_dist = float('inf')

    for city in CITIES:
        dist = geodesic((lat, lon), city['coords']).km
        is_much_closer = (nearest_dist - dist) > 8

        if is_much_closer:
            nearest_dist = dist
            nearest_city = city

    if nearest_city:
        return (nearest_city, nearest_dist)
    else:
        return (None, 0.0)


@disk_cache.cache(APP_USER_AGENT)
@rate_limit(min_interval=1.5)
def geolocate(plz: str) -> tuple[Lat, Lon] | None:
    geolocator = get_geocoder_for_service("nominatim")(user_agent=APP_USER_AGENT)
    location = geolocator.geocode(f"{plz}, Deutschland", addressdetails=True)
    log.info(f"Geocoded {plz}: {location}")
    if location is None:
        log.warning(f"No location found for {plz}")
        return None

    loc_raw = location.raw
    address = loc_raw.get('address', {})
    name = loc_raw['display_name']
    state = address.get('ISO3166-2-lvl4')

    return (name, state, location.latitude, location.longitude)


def _dedent(text: str) -> str:
    """Remove all leading whitespace from every line in `text`."""
    lines = text.splitlines()
    return "\n".join(line.lstrip() for line in lines)


def make_url(sheet_id, sheet_name: str) -> str:
    base_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}"
    _sheet_param = requests.utils.quote(sheet_name)
    return base_url + f"/gviz/tq?tqx=out:csv&sheet={_sheet_param}"


def download_gsheet(
    sheet_id: str,
    sheet_name: str = None,
    timeout: int = 10,
) -> list[dict[str, str]]:
    """
    Returns the sheet as a list of dicts (first row = headers).
    Raises informative exceptions on error.
    """
    url = make_url(sheet_id, sheet_name)
    
    response = requests.get(url, timeout=timeout)
    
    if response.status_code != 200:
        errmsg = f"""
            Failed to download sheet (status {response.status_code})
            Make sure the sheet is shared with 'Anyone with the link' or published to web.
            Response snippet: {response.text[:500]}
        """
        raise RuntimeError(_dedent(errmsg))

    # Quick sanity check - Google returns HTML error page if not accessible
    if "<html" in response.text.lower() and "sorry" in response.text.lower():
        raise PermissionError("Sheet is not publicly accessible or does not allow export.")

    reader = csv.DictReader(io.StringIO(response.text))

    for entry in reader:
        yield {
            key.lower().replace(" ", "_"): val.strip()
            for key, val in entry.items()
            if val
        }


_cli_defaults = {
    "--sheet-id"  : "1-BypxZnsRGFJ8XeuCIFyleF-4OK-ndsUvpaV6_Oi95s",
    "--sheet-name": "termine",
}


def main(argv: list[str] = sys.argv[1:]) -> int:
    subcmd, args = cli.parse_args(argv, doc=__doc__, defaults=_cli_defaults)
    cli.init_logging(args)

    data_dir = pl.Path("data")
    data_dir.mkdir(exist_ok=True)

    log.info(f"Downloading 'termine'...")
    termine = list(download_gsheet(sheet_id=args.sheet_id, sheet_name='termine'))

    with (data_dir / "termine.json").open(mode="w", encoding="utf-8") as fobj:
        json.dump(termine, fobj, indent=2, ensure_ascii=False)
    log.info(f"Saved {len(termine)} items to data/termine.json")

    www_dir = pl.Path("www")
    www_dir.mkdir(exist_ok=True)
    with (www_dir / "termine.json").open(mode="w", encoding="utf-8") as fobj:
        json.dump(termine, fobj, indent=2, ensure_ascii=False)
    log.info(f"Saved {len(termine)} items to www/termine.json")

    # Generate termine.json for the map
    event_items = []
    for termin in termine:
        link = termin.get('telegram') or termin.get('signal')
        if link:
            qr_digest = hl.sha1(link.encode("utf-8")).hexdigest()
            link_qr_path = www_dir / "img" / ("qr_" + qr_digest + ".png")
            box_size = 3
            img = qrcode.make(link, box_size=box_size, version=6, error_correction=qrcode.constants.ERROR_CORRECT_H)
            if termin.get('telegram'):
                overlay = Image.open(www_dir / "img" / "telegram_128.png")
            elif termin.get('signal'):
                overlay = Image.open(www_dir / "img" / "signal_128.png")
            else:
                raise ValueError(f"Unknown link type: {termin}")

            overlay = overlay.convert("RGBA")
            overlay = overlay.resize((box_size * 12, box_size * 12))
            img = img.convert("RGBA")
            img.paste(overlay, (img.width // 2 - overlay.width // 2, img.height // 2 - overlay.height // 2), overlay)
            img.save(link_qr_path)
        else:
            link_qr_path = None

        try:
            termin["plz"] = termin["plz"].strip()
            plz_location = geolocate(termin["plz"])
            if plz_location is None:
                continue

            plz_name, plz_state, lat, lon = plz_location
            nearest, city_dist = find_nearest_city(lat, lon)

            event_items.append({
                "name": termin.get("name", termin.get("ort", "Unknown")),
                "plz": termin["plz"],
                "state": plz_state,
                "city": nearest.get("name", "Unknown"),
                "city_dist": round(city_dist, 1),
                "coords": [lat, lon],
                "date": termin['beginn'].split(" ")[0],
                "dow": EN_DE_WEEKDAYS.get(termin['wochentag'], termin['wochentag']),
                "time": termin['uhrzeit'],
                "orga": termin.get('orga'),
                "orga_www": termin.get('orga_webseite'),
                "kontakt": termin.get('kontakt'),
                "e-mail": termin.get('e-mail'),
                "link": link,
                "link_qr": "img/" + link_qr_path.name if link_qr_path else None,
            })
        except KeyError as err:
            log.warning(f"Skipping invalid termin: {termin}")
            log.warning(f"Error: {repr(err)}")
    
    www_dir = pl.Path("www")
    www_dir.mkdir(exist_ok=True)
    with (www_dir / "termine.json").open(mode="w", encoding="utf-8") as fobj:
        json.dump(event_items, fobj, indent=2, ensure_ascii=False)
    log.info(f"Saved {len(termine)} termine to www/termine.json")

    log.info(f"Downloading 'kontakte'...")
    kontakte = list(download_gsheet(sheet_id=args.sheet_id, sheet_name='kontakte'))
    with (data_dir / "kontakte.json").open(mode="w", encoding="utf-8") as fobj:
        json.dump(kontakte, fobj, indent=2, ensure_ascii=False)
    log.info(f"Saved {len(kontakte)} items to data/kontakte.json")

    return 0


if __name__ == "__main__":
    sys.exit(main())
