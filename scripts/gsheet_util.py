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
import disk_cache
from utils import cli

from geopy.geocoders import Nominatim
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

_last_lookup = 0.0

VERSION = "plz_heatmap_prototype-v1.0"

CITIES = [
    { 'population': 3755000, 'coords': [52.5200, 13.4050], 'name': 'Berlin' },
    { 'population': 1862565, 'coords': [53.5511,  9.9937], 'name': 'Hamburg' },
    { 'population': 1505005, 'coords': [48.1351, 11.5820], 'name': 'München' },
    { 'population': 1024621, 'coords': [50.9375,  6.9603], 'name': 'Köln' },
    { 'population':  756021, 'coords': [50.1109,  8.6821], 'name': 'Frankfurt' },
    { 'population':  618685, 'coords': [51.2277,  6.7735], 'name': 'Düsseldorf' },
    { 'population':  612663, 'coords': [48.7758,  9.1829], 'name': 'Stuttgart' },
    { 'population':  611850, 'coords': [51.3397, 12.3731], 'name': 'Leipzig' },
    { 'population':  603462, 'coords': [51.5136,  7.4653], 'name': 'Dortmund' },
    { 'population':  574682, 'coords': [51.4556,  7.0116], 'name': 'Essen' },
    { 'population':  569000, 'coords': [53.0736,  8.8064], 'name': 'Bremen' },
    { 'population':  564904, 'coords': [51.0504, 13.7373], 'name': 'Dresden' },
    { 'population':  526606, 'coords': [49.4521, 11.0767], 'name': 'Nürnberg' },
    { 'population':  520290, 'coords': [52.3759,  9.7320], 'name': 'Hannover' },
    { 'population':  502000, 'coords': [51.4325,  6.7652], 'name': 'Duisburg' },
    { 'population':  366000, 'coords': [51.4818,  7.2162], 'name': 'Bochum' },
    { 'population':  358193, 'coords': [51.2637,  7.2006], 'name': 'Wuppertal' },
    { 'population':  340226, 'coords': [50.7374,  7.0982], 'name': 'Bonn' },
    { 'population':  335000, 'coords': [52.0241,  8.5290], 'name': 'Bielefeld' },
    { 'population':  321000, 'coords': [51.9624,  7.6257], 'name': 'Münster' },
    { 'population':  315000, 'coords': [49.4875,  8.4660], 'name': 'Mannheim' },
    { 'population':  310000, 'coords': [49.0069,  8.4037], 'name': 'Karlsruhe' },
    { 'population':  300089, 'coords': [50.0375,  8.2660], 'name': 'Wiesbaden' },
    { 'population':  298972, 'coords': [48.3772, 10.2522], 'name': 'Augsburg' },
    { 'population':  268000, 'coords': [51.1854,  6.4417], 'name': 'Mönchengladbach' },
    { 'population':  263000, 'coords': [51.5051,  7.0965], 'name': 'Gelsenkirchen' },
    { 'population':  252000, 'coords': [52.2659, 10.5267], 'name': 'Braunschweig' },
    { 'population':  252000, 'coords': [50.7756,  6.0836], 'name': 'Aachen' },
    { 'population':  251699, 'coords': [50.8278, 12.9214], 'name': 'Chemnitz' },
    { 'population':  249132, 'coords': [54.3233, 10.1228], 'name': 'Kiel' },
    { 'population':  240114, 'coords': [52.1205, 11.6276], 'name': 'Magdeburg' },
    { 'population':  236236, 'coords': [47.9990,  7.8421], 'name': 'Freiburg' },
    { 'population':  227000, 'coords': [51.4833, 11.9667], 'name': 'Halle (Saale)' },
    { 'population':  227000, 'coords': [51.3392,  6.5862], 'name': 'Krefeld' },
    { 'population':  219549, 'coords': [50.9848, 11.0299], 'name': 'Erfurt' },
    { 'population':  217272, 'coords': [49.9929,  8.2473], 'name': 'Mainz' },
    { 'population':  217061, 'coords': [53.8655, 10.6866], 'name': 'Lübeck' },
    { 'population':  210000, 'coords': [51.4781,  6.8625], 'name': 'Oberhausen' },
    { 'population':  205307, 'coords': [54.0924, 12.0991], 'name': 'Rostock' },
    { 'population':  201048, 'coords': [51.3127,  9.4797], 'name': 'Kassel' },
    { 'population':  182971, 'coords': [49.2327,  6.9962], 'name': 'Saarbrücken' },
    { 'population':  176110, 'coords': [49.4718,  8.4512], 'name': 'Ludwigshafen' },
    { 'population':  155756, 'coords': [49.4103,  8.6971], 'name': 'Heidelberg' },
    { 'population':  151389, 'coords': [49.0134, 12.1016], 'name': 'Regensburg' },
    { 'population':  115298, 'coords': [50.3569,  7.5890], 'name': 'Koblenz' },
    { 'population':  108056, 'coords': [50.9271, 11.5892], 'name': 'Jena' },
    { 'population':  104342, 'coords': [49.7597,  6.6415], 'name': 'Trier' },
]

def find_nearest_city(lat: float, lon: float) -> tuple[dict, float] | None:
    nearest_city = None
    nearest_dist = float('inf')

    for city in CITIES:
        dist = geodesic((lat, lon), city['coords']).km
        # breakpoint()
        is_much_closer = (nearest_dist - dist) > 8

        if is_much_closer:
            nearest_dist = dist
            nearest_city = city

    if nearest_city:
        return (nearest_city, nearest_dist)
    return None


@disk_cache.cache(VERSION)
def geolocate(plz: str) -> tuple[Lat | None, Lon | None]:
    global _last_lookup
    wait = max(0.01, 1.5 - (time.time() - _last_lookup))
    _last_lookup = time.time()
    time.sleep(wait)  # Rate limit

    geolocator = Nominatim(user_agent=VERSION)
    location = geolocator.geocode(f"{plz} Germany")
    log.info(f"Geocoded {plz}: {location}")
    if location:
        return (location.latitude, location.longitude)
    else:
        log.warning(f"No location found for {plz}")
        return (None, None)


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
    args = cli.parse_args(argv, doc=__doc__, defaults=_cli_defaults)
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
            link_qr_path = www_dir / "img" / ("qr_" + hl.sha1(link.encode("utf-8")).hexdigest() + ".png")
            img = qrcode.make(link, version=6, error_correction=qrcode.constants.ERROR_CORRECT_M)
            if termin.get('telegram'):
                overlay = Image.open(www_dir / "img" / "telegram_128.png")
            elif termin.get('signal'):
                overlay = Image.open(www_dir / "img" / "signal_128.png")
            else:
                raise ValueError(f"Unknown link type: {termin}")

            overlay = overlay.convert("RGBA")
            overlay = overlay.resize((96, 96))
            img = img.convert("RGBA")
            img.paste(overlay, (img.width // 2 - overlay.width // 2, img.height // 2 - overlay.height // 2), overlay)
            img.save(link_qr_path)
        else:
            link_qr_path = None

        termin["plz"] = termin["plz"].strip()
        lat, lon = geolocate(termin["plz"])
        if not (lat and lon):
            continue

        nearest_result = find_nearest_city(lat, lon)
        if nearest_result:
            nearest, city_dist = nearest_result
            city_name = nearest['name']
        else:
            city_name = "Unknown"
            city_dist = 0.0

        try:
            event_items.append({
                "name": termin.get("name", termin.get("ort", "Unknown")),
                "plz": termin["plz"],
                "city": city_name,
                "city_dist": round(city_dist, 1),
                "coords": [lat, lon],
                "date": termin['beginn'].split(" ")[0],
                "dow": EN_DE_WEEKDAYS.get(termin['wochentag'], termin['wochentag']),
                "time": termin['beginn'].split(" ")[1] + " - " + termin['ende'].split(" ")[1],
                "orga": termin.get('orga'),
                "orga_www": termin.get('orga_webseite'),
                "kontakt": termin.get('kontakt'),
                "link": link,
                "link_qr": "img/" + link_qr_path.name if link_qr_path else None,
            })
        except Exception as err:
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
