#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = [
#   "pudb", "ipython",
#   "requests~=2.32.3",
#   "geopy~=2.4.1",
#   "qrcode~=8.2",
#   "Pillow~=12.1.0",
#   "google-api-python-client~=2.188.0",
#   "google-auth~=2.38.0",
# ]
# ///
"""
Google Sheets utility for freiheitliche-stammtische.de.

Usage:
    gsheet_util.py [validate] [--sheet-id <id>]
    gsheet_util.py [sync] [--sheet-id <id>] [--sheet-name <name>]

Commands:
    validate        Validate sheet
    sync            Download sheet to data/ and www/ (default)

Options:
    --sheet-id <sheet_id>      Long ID from the Google Sheets URL
    --sheet-name <sheet_name>  Name of the tab (e.g. 'termine')
    -v, --verbose              Enable verbose logging
    -q, --quiet                Enable quiet logging
    -h, --help                 Show this help message and exit
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
import datetime as dt

import qrcode
import requests
from utils import disk_cache
from utils import cli
from utils.decorators import rate_limit

import googleapiclient.discovery as g_discovery
import google.oauth2.service_account as g_service_account

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
def geolocate(plz: str) -> tuple[str, str, Lat, Lon] | None:
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


class Location(typ.NamedTuple):
    plz_name: str
    plz_state: str
    lat: Lat
    lon: Lon
    nearest: dict[str, typ.Any]
    city_dist: float


def plz_location_lookup(plz: str) -> Location | None:
    plz_location = geolocate(plz)
    if plz_location:
        plz_name, plz_state, lat, lon = plz_location
        nearest, city_dist = find_nearest_city(lat, lon)
        return Location(plz_name, plz_state, lat, lon, nearest, city_dist)
    else:
        return None


def _dedent(text: str) -> str:
    """Remove all leading whitespace from every line in `text`."""
    lines = text.splitlines()
    return "\n".join(line.lstrip() for line in lines)


def make_url(sheet_id, sheet_name: str) -> str:
    base_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}"
    _sheet_param = requests.utils.quote(sheet_name)
    return base_url + f"/gviz/tq?tqx=out:csv&sheet={_sheet_param}"


def _get_sheets_service(creds_path: str | pl.Path | None = None):
    """
    Returns an authorized Google Sheets API service object.
    Searches in 'creds/' if no path is provided.
    """
    if creds_path is None:
        creds_dir = pl.Path("creds")
        if creds_dir.exists():
            json_files = list(creds_dir.glob("*.json"))
            if json_files:
                creds_path = json_files[0]
                log.info(f"Using credentials from {creds_path}")

    if not creds_path or not pl.Path(creds_path).exists():
        log.error("Google Service Account credentials not found.")
        log.error("Please provide --creds <path> or place a JSON key in the 'creds/' directory.")
        sys.exit(1)

    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = g_service_account.Credentials.from_service_account_file(
        str(creds_path), scopes=scopes
    )
    return g_discovery.build("sheets", "v4", credentials=creds, cache_discovery=False)


def _append_gsheet(service, sheet_id: str, sheet_name: str, rows: list[list[typ.Any]]):
    """Appends rows to the specified sheet."""
    range_name = f"{sheet_name}!A1"
    body = {"values": rows}
    result = (
        service.spreadsheets()
        .values()
        .append(
            spreadsheetId=sheet_id,
            range=range_name,
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body=body,
        )
        .execute()
    )
    updates = result.get('updates', {})
    updated_cells = updates.get('updatedCells', 0)
    log.info(f"{updated_cells} cells appended.")
    return result


def _update_gsheet(service, sheet_id: str, sheet_name: str, range_name: str, rows: list[list[typ.Any]]):
    """Updates a specific range in the specified sheet."""
    full_range = f"{sheet_name}!{range_name}"
    body = {"values": rows}
    result = (
        service.spreadsheets()
        .values()
        .update(
            spreadsheetId=sheet_id,
            range=full_range,
            valueInputOption="RAW",
            body=body,
        )
        .execute()
    )
    updated_cells = result.get('updatedCells', 0)
    log.info(f"{updated_cells} cells updated.")
    return result


def _normalize_key(key: str) -> str:
    return key.strip().lower().replace(" ", "_")


class GSheet:
    def __init__(self, sheet_id: str, creds_path: str | pl.Path | None = None):
        self.sheet_id = sheet_id
        self.service = _get_sheets_service(creds_path)
        self._headers_cache = {}

    def _get_headers(self, sheet_name: str) -> list[str]:
        if sheet_name not in self._headers_cache:
            # We fetch a wide range to get all potential headers in the first row
            range_name = f"{sheet_name}!A1:Z1"
            try:
                result = (
                    self.service.spreadsheets()
                    .values()
                    .get(spreadsheetId=self.sheet_id, range=range_name)
                    .execute()
                )
                values = result.get("values", [])
                if values:
                    self._headers_cache[sheet_name] = [h.strip() for h in values[0]]
                else:
                    self._headers_cache[sheet_name] = []
            except Exception as ex:
                # If sheet doesn't exist, create it
                if "Unable to parse range" in str(ex):
                    log.info(f"Sheet '{sheet_name}' not found. Creating it.")
                    body = {"requests": [{"addSheet": {"properties": {"title": sheet_name}}}]}
                    self.service.spreadsheets().batchUpdate(spreadsheetId=self.sheet_id, body=body).execute()
                    self._headers_cache[sheet_name] = []
                else:
                    raise
        return self._headers_cache[sheet_name]

    def _get_sheet_id(self, sheet_name: str) -> int:
        spreadsheet = self.service.spreadsheets().get(spreadsheetId=self.sheet_id).execute()
        sheets = spreadsheet.get('sheets', [])
        for s in sheets:
            if s.get('properties', {}).get('title') == sheet_name:
                return s.get('properties', {}).get('sheetId')
        raise ValueError(f"Sheet '{sheet_name}' not found.")

    def read(self, sheet_name: str) -> list[dict[str, str]]:
        """Returns the sheet as a list of dicts (first row = headers)."""
        range_name = f"{sheet_name}!A1:Z5000"
        result = (
            self.service.spreadsheets()
            .values()
            .get(spreadsheetId=self.sheet_id, range=range_name)
            .execute()
        )
        values = result.get("values", [])
        if not values:
            return []

        headers = [_normalize_key(h) for h in values[0]]
        rows = []
        for row_values in values[1:]:
            row_dict = {}
            for i, val in enumerate(row_values):
                if i < len(headers):
                    key = headers[i]
                    row_dict[key] = val.strip()
            if row_dict:
                rows.append(row_dict)
        return rows

    def append(self, sheet_name: str, rows: list[dict[str, typ.Any]]):
        """Appends dictionaries as rows, matching keys to existing headers."""
        headers = self._get_headers(sheet_name)
        norm_headers = [_normalize_key(h) for h in headers]

        # 1. Identify all new keys and update headers if necessary
        # We want to preserve the order in which we see new keys
        new_keys = []
        seen_keys = set(norm_headers)
        for row_dict in rows:
            for key in row_dict.keys():
                normalized_key = _normalize_key(key)
                if normalized_key not in seen_keys:
                    new_keys.append(normalized_key)
                    seen_keys.add(normalized_key)
        
        if new_keys:
            norm_headers.extend(new_keys)
            _update_gsheet(
                service=self.service,
                sheet_id=self.sheet_id,
                sheet_name=sheet_name,
                range_name="A1:Z1",
                rows=[norm_headers]
            )
            self._headers_cache[sheet_name] = norm_headers

        # 2. Build row lists using the (potentially updated) norm_headers
        row_lists = []
        for row_dict in rows:
            row_list = [row_dict.get(h, "") for h in norm_headers]
            row_lists.append(row_list)

        result = _append_gsheet(self.service, self.sheet_id, sheet_name, row_lists)
        
        # 3. Inherit formatting from preceding row
        try:
            updates = result.get('updates', {})
            updated_range = updates.get('updatedRange', '')  # e.g. "Sheet1!A10:Z10"
            if updated_range and "!" in updated_range:
                range_part = updated_range.split("!")[1]
                start_cell = range_part.split(":")[0]
                # Extract row number from cell like "A10"
                import re
                match = re.search(r"(\d+)", start_cell)
                if match:
                    start_row_idx = int(match.group(1))
                    if start_row_idx > 1:
                        sheet_id = self._get_sheet_id(sheet_name)
                        num_rows = updates.get('updatedRows', 1)
                        
                        # Copy format from start_row_idx - 1 to [start_row_idx, start_row_idx + num_rows - 1]
                        body = {
                            "requests": [
                                {
                                    "copyPaste": {
                                        "source": {
                                            "sheetId": sheet_id,
                                            "startRowIndex": start_row_idx - 2,
                                            "endRowIndex": start_row_idx - 1,
                                        },
                                        "destination": {
                                            "sheetId": sheet_id,
                                            "startRowIndex": start_row_idx - 1,
                                            "endRowIndex": start_row_idx - 1 + num_rows,
                                        },
                                        "pasteType": "PASTE_FORMAT"
                                    }
                                }
                            ]
                        }
                        self.service.spreadsheets().batchUpdate(spreadsheetId=self.sheet_id, body=body).execute()
                        log.info(f"Inherited formatting from row {start_row_idx - 1} for {num_rows} rows.")
        except Exception as e:
            log.warning(f"Failed to inherit formatting: {e}")

        return result

    def update(self, sheet_name: str, range_name: str, rows: list[dict[str, typ.Any]]):
        """
        Updates a specific range using dictionaries.
        NOTE: This assumes the range structure matches the column order.
        """
        headers = self._get_headers(sheet_name)
        norm_headers = [_normalize_key(h) for h in headers]

        row_lists = []
        for row_dict in rows:
            row_list = []
            for norm_h in norm_headers:
                row_list.append(row_dict.get(norm_h, ""))
            row_lists.append(row_list)

        return _update_gsheet(self.service, self.sheet_id, sheet_name, range_name, row_lists)

    def log(self, message: str, level: int = logging.INFO):
        """Writes a message to the 'log' sheet."""
        log.log(level=level, msg=message)
        timestamp = dt.datetime.now().isoformat(sep=" ")
        level_name = logging.getLevelName(level)
        row = {
            "timestamp": timestamp,
            "level": level_name,
            "message": message,
        }
        return self.append("log", [row])

    def delete_row(self, sheet_name: str, row_index: int):
        """
        Deletes a row from the specified sheet.
        row_index: 1-indexed (header is usually 1, first data row is 2).
        """
        sheet_id = self._get_sheet_id(sheet_name)
        
        body = {
            "requests": [
                {
                    "deleteDimension": {
                        "range": {
                            "sheetId": sheet_id,
                            "dimension": "ROWS",
                            "startIndex": row_index - 1,
                            "endIndex": row_index
                        }
                    }
                }
            ]
        }
        return self.service.spreadsheets().batchUpdate(spreadsheetId=self.sheet_id, body=body).execute()


    def debug(self, message: str, *args, **kwargs):
        return self.log(message, level=logging.DEBUG, *args, **kwargs)

    def info(self, message: str, *args, **kwargs):
        return self.log(message, level=logging.INFO, *args, **kwargs)

    def warning(self, message: str, *args, **kwargs):
        return self.log(message, level=logging.WARNING, *args, **kwargs)

    def warn(self, message: str, *args, **kwargs):
        return self.warning(message, *args, **kwargs)

    def error(self, message: str, *args, **kwargs):
        return self.log(message, level=logging.ERROR, *args, **kwargs)


def download_gsheet(
    sheet_id: str,
    sheet_name: str = None,
    timeout: int = 10,
) -> list[dict[str, str]]:
    """
    Returns the sheet as a list of dicts (first row = headers).
    Raises informative exceptions on error.
    """
    # first see if it works without authentication
    url = make_url(sheet_id, sheet_name)
    response = requests.get(url, timeout=timeout)

    if response.status_code == 200:
        # Quick sanity check - Google returns HTML error page if not accessible
        if "<html" in response.text.lower() and "sorry" in response.text.lower():
            raise PermissionError("Sheet is not publicly accessible or does not allow export.")

        reader = csv.DictReader(io.StringIO(response.text))
        for entry in reader:
            yield {
                _normalize_key(key): val.strip()
                for key, val in entry.items()
                if val
            }
    else:
        # fallback to GSheet API which requires authentication
        sheet = GSheet(sheet_id=sheet_id)
        sheet_rows = sheet.read(sheet_name)
        for entry in sheet_rows:
            yield {key: val for key, val in entry.items() if val}


def sync_cmd(args) -> int:
    data_dir = pl.Path("data")
    data_dir.mkdir(exist_ok=True)

    log.info(f"Downloading 'termine'...")
    termine = list(download_gsheet(sheet_id=args.sheet_id, sheet_name='termine'))
    termine.sort(key=lambda termin: termin.get('beginn', "2000-01-01"))

    data_termine = json.dumps(termine, indent=2, ensure_ascii=False)
    with (data_dir / "termine.json").open(mode="w", encoding="utf-8") as fobj:
        fobj.write(data_termine)

    log.info(f"Saved {len(termine)} items to data/termine.json")

    www_dir = pl.Path("www")
    www_dir.mkdir(exist_ok=True)

    www_termine = json.dumps(termine, indent=2, ensure_ascii=False)
    with (www_dir / "termine.json").open(mode="w", encoding="utf-8") as fobj:
        fobj.write(www_termine)

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
            location = plz_location_lookup(termin["plz"])
            if location is None:
                continue

            event_items.append({
                "name": termin.get("name", termin.get("ort", "Unknown")),
                "plz": termin["plz"],
                "state": location.plz_state,
                "city": location.nearest.get("name", "Unknown"),
                "city_dist": round(location.city_dist, 1),
                "coords": [location.lat, location.lon],
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


def validate_cmd(args) -> int:
    sheet = GSheet(sheet_id=args.sheet_id)
    sheet.log("Validating sheet...")
    kontakte = sheet.read('kontakte')
    kontakt_names = [k['name'] for k in kontakte if k.get('name')]
    assert len(kontakt_names) == len(set(kontakt_names))

    termine = sheet.read('termine')
    for termin in termine:
        if not termin.get('name') or termin.get('beginn'):
            continue

        if not termin.get('kontakt'):
            log.warning(f"Termin ohne kontakt: {termin}")
        elif termin['kontakt'] not in kontakt_names:
            log.warning(f"Termin mit fehlendem kontakt: {termin}")

    log.info("Test passed!")
    return 0


PROD_SHEET = "1-BypxZnsRGFJ8XeuCIFyleF-4OK-ndsUvpaV6_Oi95s"
TEST_SHEET = "15QeC3F4CPHLNjroghRXHDjO8oBC2wmJBPhTLHF_5XOs"

_cli_defaults = {
    "--sheet-id"  : PROD_SHEET,
    # "--sheet-id"  : TEST_SHEET,
    "--sheet-name": "termine",
}


def main(argv: list[str] = sys.argv[1:]) -> int:
    subcmd, args = cli.parse_args(argv, doc=__doc__, defaults=_cli_defaults)
    cli.init_logging(args)

    if subcmd in (None, "sync"):
        return sync_cmd(args)
    if subcmd == "validate":
        return validate_cmd(args)
    else:
        log.error(f"Unknown subcommand: {subcmd}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
