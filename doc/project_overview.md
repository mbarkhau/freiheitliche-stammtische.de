# Freiheitliche Stammtische

Static website for `freiheitliche-stammtische.de`. Visualization of events and meetups of the libertarian movement on a map of Germany.

## Directory Structure

```
.
├── Makefile            # Build and utility commands
├── doc/                # Documentation
├── data/               # Data downloaded from google spreadsheet
├── scripts/            # Python scripts for data processing and geocoding
│   ├── disk_cache.py   # Caching utility for geocoding results
│   ├── gsheet_util.py  # Google Sheets downloader and geocoder
└── www/                # Web frontend assets
    ├── index.html      # Main entry point (uses jsvectormap)
    ├── map_*.js        # Map data files for DACH region (Germany, Austria, Switzerland)
    └── ...             # CSS and JS libraries (jsvectormap)
```

## Components

### 1. Data Processing (`scripts/`)

-   **`gsheet_util.py`**: Fetches data from a public Google Sheet (default ID: `1-BypxZnsRGFJ8XeuCIFyleF-4OK-ndsUvpaV6_Oi95s`). It retrieves "termine" (events) and "kontakte" (contacts) and can geocode postal codes (PLZ) to latitude/longitude using `geopy` (Nominatim).
-   **`plz_heatmap.py`**: A standalone script that takes a list of postal codes, geocodes them, and generates an interactive heatmap using `folium`. The output is saved as `germany_plz_heatmap.html`.
-   **`disk_cache.py`**: A utility to cache function results to disk, primarily used to avoid hitting geocoding API rate limits.

### 2. Web Frontend (`www/`)

-   **`index.html`**: A simple HTML page setup to display a map using `jsvectormap`.
-   **Map Data**: Includes map definitions for Germany (`map_de_mill.js`), Austria (`map_at_mill.js`), and Switzerland (`map_ch_mill.js`).
-   **Current State**: The `initMap` function in `index.html` is set up to accept data, but the `mapData` object is currently empty. It seems designed to visualize regional data (likely the contacts or events).

### 3. Build System (`Makefile`)

The `Makefile` contains targets for building the web assets and serving the site. However, it appears to be out of sync with the current file structure:
-   It references a `src` directory (e.g., `src/build_html.py`, `src/update_json.py`) which **does not exist** in the current file listing.
-   It references a `templates` directory which is also **missing**.
-   It attempts to use `uv` (Python package manager) and `bun` (JavaScript runtime) for build tasks.

## Observations

-   The project seems to be in a transitional state or has missing source files (`src/`, `templates/`).
-   There are two distinct map visualization approaches visible: one using Python/Folium (`plz_heatmap.py`) and one using JS/jsvectormap (`www/index.html`).
-   The data source appears to be a Google Sheet, with `gsheet_util.py` being the bridge to fetch that data.
