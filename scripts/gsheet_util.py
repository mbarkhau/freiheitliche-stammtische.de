#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = [
#   "pudb", "ipython",
#   "requests",
#   "geopy",
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
import argparse
import typing as typ

import requests
import disk_cache
from utils import cli

from geopy.geocoders import Nominatim

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

@disk_cache.cache
def geolocate(plz: str) -> tuple[Lat | None, Lon | None]:
    global _last_lookup
    wait = max(0.01, 1.5 - (time.time() - _last_lookup))
    _last_lookup = time.time()
    time.sleep(wait)  # Rate limit

    geolocator = Nominatim(user_agent="plz_heatmap_prototype-v1.0")
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

    # Generate markers.json for the map
    markers = []
    for entry in termine:
        try:
            entry["plz"] = entry["plz"].strip()
            lat, lon = geolocate(entry["plz"])
            if lat and lon:
                markers.append({
                    "name": entry.get("name", entry.get("ort", "Unknown")),
                    "plz": entry["plz"],
                    "coords": [lat, lon],
                    "date": entry['beginn'].split(" ")[0],
                    "dow": EN_DE_WEEKDAYS.get(entry['wochentag'], entry['wochentag']),
                    "time": entry['beginn'].split(" ")[1] + " - " + entry['ende'].split(" ")[1],
                    "orga": entry.get('orga'),
                    "kontakt": entry.get('kontakt'),
                    "link": entry.get('signal') or entry.get('telegram'),
                    # "style": {"fill": "blue"} # Optional: different color for these markers
                })
        except Exception as err:
            log.warning(f"Skipping invalid entry: {entry}")
            log.warning(f"Error: {err}")
    
    www_dir = pl.Path("www")
    www_dir.mkdir(exist_ok=True)
    with (www_dir / "markers.json").open(mode="w", encoding="utf-8") as fobj:
        json.dump(markers, fobj, indent=2, ensure_ascii=False)
    log.info(f"Saved {len(markers)} markers to www/markers.json")

    log.info(f"Downloading 'kontakte'...")
    kontakte = list(download_gsheet(sheet_id=args.sheet_id, sheet_name='kontakte'))
    with (data_dir / "kontakte.json").open(mode="w", encoding="utf-8") as fobj:
        json.dump(kontakte, fobj, indent=2, ensure_ascii=False)
    log.info(f"Saved {len(kontakte)} items to data/kontakte.json")

    return 0


if __name__ == "__main__":
    sys.exit(main())
