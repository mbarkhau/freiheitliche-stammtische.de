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
Update coords for data/cities.json.

Usage:
    update_city_coords.py

Options:
    -v, --verbose         Enable verbose logging
    -q, --quiet           Enable quiet logging
    -h, --help            Show this help message and exit
"""
import io
import sys
import time
import json
import logging
import pathlib as pl
import hashlib as hl
import argparse
import typing as typ

from geopy.geocoders import get_geocoder_for_service
# from geopy.distance import geodesic

from utils import cli
from utils import disk_cache
from utils import decorators

log = logging.getLogger(name="update_cities_coords.py")


APP_USER_AGENT = "freiheitliche-stammtische.de-city-coords-v0.09"


@disk_cache.cache(APP_USER_AGENT)
@decorators.rate_limit(min_interval=1.5)
def geolocate(city: str) -> tuple[str, str, str, int, float, float] | None:
    geolocator = get_geocoder_for_service("nominatim")(user_agent=APP_USER_AGENT)

    location = geolocator.geocode(f"{city}, Deutschland", addressdetails=True)

    if location:
        loc_raw = location.raw
        if loc_raw['addresstype'] in ('city', 'town', 'village'):
            address = loc_raw.get('address', {})
            state = address.get('ISO3166-2-lvl4')

            german_name = loc_raw['display_name'].split(",")[0]
            return (
                german_name,
                loc_raw['display_name'],
                state,
                loc_raw['place_rank'],
                location.latitude,
                location.longitude
            )

        if "oe" in city or "ae" in city or "ue" in city:
            cleaned_city = (
                city
                .replace("oe", "ö")
                .replace("ae", "ä")
                .replace("ue", "ü")
            )
            return geolocate(cleaned_city)

    return None


_cli_defaults = {
    "--verbose": True,
}


def read_json_list(path: str) -> list:
    path_obj = pl.Path(path)
    if path_obj.exists():
        with path_obj.open(mode="r", encoding="utf-8") as fobj:
            return json.load(fobj)
    else:
        return []


def main(argv: list[str] = sys.argv[1:]) -> int:
    args = cli.parse_args(argv, doc=__doc__, defaults=_cli_defaults)
    cli.init_logging(args)

    # Source of truth for populations and names
    city_populations = read_json_list("data/city_populations.json")
    cities_data = read_json_list("data/cities.json")
    for city in cities_data:
        if not city.get('rank'):
            print(city)
    cities_by_name = {city['name']: city for city in cities_data}

    return
    
    for city_name, population in city_populations.items():
        loc_info = geolocate(city_name)
        if loc_info is None:
            log.warning(f"Could not geolocate {city_name}")
            continue

        city_name, full_name, state, loc_rank, lat, lon = loc_info
        log.info(f"Geolocated {city_name}: {full_name}, state={state}, rank={loc_rank}, lat={lat}, lon={lon}")
    
        new_entry = {
            'name': city_name,
            'population': population,
            'full_name': full_name,
            'state': state,
            'rank': loc_rank,
            'coords': [lat, lon],
        }
        old_entry = cities_by_name.get(city_name)
        if new_entry == old_entry:
            continue

        cities_by_name[city_name] = new_entry
            
        cities_path = pl.Path("data/cities.json")
        cities_path_tmp = pl.Path("data/cities.json.tmp")
        with cities_path_tmp.open(mode="w", encoding="utf-8") as fobj:
            new_cities_data = list(cities_by_name.values())
            json.dump(new_cities_data, fobj, indent=2, ensure_ascii=False)

        cities_path_tmp.replace(cities_path)
        log.info(f"Updated {city_name}")

    return 0


if __name__ == "__main__":
    sys.exit(main())