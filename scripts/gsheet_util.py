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
Google Sheets → CSV downloader

Works with sheets shared as "Anyone with the link can view".
"""

import io
import sys
import csv
import time
import argparse
import typing as typ

import requests
import disk_cache

from geopy.geocoders import Nominatim

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
    print(f"Geocoded {plz}: {location}")
    if location:
        return (location.latitude, location.longitude)
    else:
        print(f"No location found for {plz}")
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
            key.lower().replace(" ", "_"): val
            for key, val in entry.items()
            if val
        }


DEFAULT_SHEET_ID = "1-BypxZnsRGFJ8XeuCIFyleF-4OK-ndsUvpaV6_Oi95s"
DEFAULT_SHEET_NAME = "termine"


def init_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Download Google Sheet → CSV (no pandas, pipeline-ready)"
    )
    parser.add_argument(
        "sheet_id",
        nargs="?",
        default=DEFAULT_SHEET_ID,
        help="Long ID from the Google Sheets URL"
    )
    parser.add_argument(
        "--sheet-name",
        nargs="?",
        default=DEFAULT_SHEET_NAME,
        help="Name of the tab (e.g. 'termine'"
    )
    return parser


def main(args: list[str] | None = sys.argv[1:]) -> int:
    parser = init_arg_parser()
    args = parser.parse_args(args)

    termine = download_gsheet(sheet_id=args.sheet_id, sheet_name='termine')
    for termin in termine:
        print(termin)

    print()

    kontakte = download_gsheet(sheet_id=args.sheet_id, sheet_name='kontakte')
    for kontakt in kontakte:
        print(kontakt)

    return 0


if __name__ == "__main__":
    sys.exit(main())
