#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = [
#   "ipython", "pudb",
#   "requests",
#   "geopy",
#   "folium"
# ]
# ///
import time
import collections
from geopy.geocoders import Nominatim
import folium
from folium.plugins import HeatMap

from lib import disk_cache

# The list of postal codes from postleitzahlen.txt
plz_list = [
    '03048', '83620', '39116', '73278', '86807', '68309', '85238', '83620', '44319', '63150',
    '68309', '04317', '63110', '18507', '80804', '94124', '56242', '42719', '49549', '83115',
    '76761', '29303', '64569', '83486', '83313', '84489', '01069', '81825', '80539', '82178',
    '17331', '73117', '83342', '82438', '63073', '81927', '83714', '44227', '40589', '34454',
    '45699', '67434', '78315', '14532', '16540', '14469', '22089', '20539', '36103', '83022',
    '21709', '25469', '90489', '01689', '04178', '20255', '94253', '21481', '48249', '72622',
    '79241', '15838', '66740', '90489', '63897', '25421', '27804', '72184', '03130', '01665',
    '05121', '69168', '64342', '31139', '83661', '21398', '59821', '99330', '82362', '71263',
    '37124', '02977', '74889', '13088', '72270', '13587', '16515', '95709', '35392', '37308',
    '06110', '80539', '55270', '32699', '67742', '33659', '97957', '38350', '60138', '06449',
    '85774', '95448', '40427', '61118', '97922', '64319', '86179', '36304', '67655', '72270',
    '36358', '40476', '91241', '07381', '99084', '40629', '07586', '45239', '73760', '94166',
    '40468', '93164', '50129', '06406', '25358', '89155', '69115', '66386', '01050', '67354',
    '50100', '76761', '80339', '85293', '26721', '76185', '03130', '29584', '31089', '65933',
    '23845', '53359', '96346', '45889', '36381', '04571', '72477', '84489', '68642', '82152',
    '79271', '53840', '28879', '91336', '89160', '06372', '36364', '85049', '82405', '93053',
    '74076', '91785', '87761', '53919', '97877', '24816', '81539', '39124', '30655', '90433',
    '41189', '24536', '13355', '01662', '26632', '27729', '90513', '41464', '76767', '23611',
    '77652', '50829', '85391', '88079', '99330', '77654', '02689', '21266'
]

# Step 1: Count frequencies to weight the heatmap
counts = collections.Counter(plz_list)

Lat = float
Lon = float

last_lookup = 0.0

# Step 2: Geocode unique PLZ to lat/lon
# - add sleep to respect rate limits
# - cache to speed up calls between script runs
@disk_cache.cache
def geolocate(plz: str) -> (Lat, Lon):
    global last_lookup
    wait = max(0.01, 1.5 - (time.time() - last_lookup))
    last_lookup = time.time()
    time.sleep(wait)  # Rate limit

    geolocator = Nominatim(user_agent="plz_heatmap_prototype-v1.0")
    location = geolocator.geocode(f"{plz} Germany")
    print(f"Geocoded {plz}: {location}")
    if location:
        return (location.latitude, location.longitude)
    else:
        print(f"No location found for {plz}")
        return (None, None)


@disk_cache.cache
def _location_by_coords(lat: float, lon: float) -> dict:
    global last_lookup
    wait = max(0.01, 1.5 - (time.time() - last_lookup))
    last_lookup = time.time()
    time.sleep(wait)  # Rate limit

    geolocator = Nominatim(user_agent="plz_heatmap_prototype-v1.0")
    location = geolocator.reverse(f"{lat}, {lon}", language='de', timeout=5)
    return location.raw


def location_name(lat: float, lon: float) -> str:
    loc_raw = _location_by_coords(lat, lon)
    addr = loc_raw['address']
    if addr['country'] == "Deutschland":
        if 'city' in addr:
            region = addr['city']
        elif 'county' in addr:
            region = addr['county']
        elif 'town' in addr:
            region = addr['town']
        else:
            region = "unbekannt"
            breakpoint()

        if 'state' in addr:
            return f"{addr['state']}, {region}"
        else:
            return f"{region}"
    else:
        return "Ausland"


lat_coords = collections.defaultdict(list)
lon_coords = collections.defaultdict(list)


def loc_center(lat_k: float, lon_k: float) -> tuple[float, float]:
    lats = sorted(lat_coords[lat_k, lon_k])
    lons = sorted(lon_coords[lat_k, lon_k])
    lat = sum(lats) / len(lats)
    lon = sum(lons) / len(lons)
    return (lat, lon)


lat_resolution = 0.9
lon_resolution = lat_resolution * 2

locations = collections.defaultdict(int)
location_plz = collections.defaultdict(list)

for plz, count in counts.items():
    try:
        lat, lon = geolocate(plz)
        lat_k = round(lat * lat_resolution) / lat_resolution
        lon_k = round(lon * lon_resolution) / lon_resolution
        locations[lat_k, lon_k] += count
        location_plz[lat_k, lon_k].append(plz)
        lat_coords[lat_k, lon_k].append(lat)
        lon_coords[lat_k, lon_k].append(lon)
    except Exception as err:
        print(f"Error geocoding {plz}: {repr(err)}")


print(f"Processed {len(plz_list)} entries with {len(locations)} unique locations.")


for (lat_k, lon_k), plz_list in location_plz.items():
    lat, lon = loc_center(lat_k, lon_k)
    name = location_name(lat, lon)
    print(len(plz_list), name, plz_list)


# Step 3: Prepare data for heatmap (repeat points based on frequency for weighting)
data = []
for (lat_k, lon_k), count in locations.items():
    lat, lon = loc_center(lat_k, lon_k)

    for _ in range(count):
        data.append([lat, lon, 1])  # Intensity=1 per occurrence; adjust if needed


# Step 4: Generate interactive heatmap with folium
if data:
    m = folium.Map(location=[51.1657, 10.4515], zoom_start=6)  # Center on Germany
    HeatMap(data, radius=8, blur=9).add_to(m)  # Tune radius/blur for visual
    m.save('germany_plz_heatmap.html')
    print("Heatmap saved to 'germany_plz_heatmap.html'. Open in your browser to view.")
else:
    print("No geocoded data available for heatmap.")