"""
BAG Buildings API Interface

This module fetches building footprint data from the Dutch BAG 
(Basisregistratie Adressen en Gebouwen) API, with support for spatial
tiling, parallel requests, and local caching.
"""

import requests
import numpy as np
import math
import logging
import os
import pickle
from concurrent.futures import ThreadPoolExecutor, as_completed
from pyproj import Transformer


# Configure module logger
logger = logging.getLogger(__name__)


class BAGAPIError(Exception):
    """Exception raised for BAG API errors."""
    
    def __init__(self, message, status_code=None, response_text=None):
        self.status_code = status_code
        self.response_text = response_text
        super().__init__(message)


def _get_api_key():
    """
    Retrieve BAG API key from environment variable.
    
    Returns
    -------
    str or None
        API key if found in environment, None otherwise.
    """
    return os.environ.get('BAG_API_KEY')


def fetch_buildings_from_BAG(bounding_box, api_key=None):
    """
    Fetches building data from the BAG API using spatial tiling and parallel requests.

    Parameters
    ----------
    bounding_box : list
        [min_lon, min_lat, max_lon, max_lat] in WGS84.
    api_key : str, optional
        API key for BAG Individuele Bevragingen. If not provided, will attempt
        to read from BAG_API_KEY environment variable.

    Returns
    -------
    list
        List of building dicts from the BAG API.
    
    Raises
    ------
    BAGAPIError
        If API request fails due to authentication, rate limiting, or server errors.
    ValueError
        If no API key is provided or found in environment.
    """
    # Resolve API key
    resolved_key = api_key or _get_api_key()
    if not resolved_key:
        raise ValueError(
            "BAG API key required. Either pass api_key parameter or set "
            "BAG_API_KEY environment variable."
        )
    
    base_url = "https://api.bag.kadaster.nl/lvbag/individuelebevragingen/v2/panden"
    transformer = Transformer.from_crs("EPSG:4326", "EPSG:28992", always_xy=True)
    minx, miny = transformer.transform(bounding_box[0], bounding_box[1])
    maxx, maxy = transformer.transform(bounding_box[2], bounding_box[3])

    width = maxx - minx
    height = maxy - miny
    total_area = width * height
    max_area = 250000
    n_tiles = math.ceil(total_area / max_area)
    n_cols = math.ceil(math.sqrt(n_tiles * width / height))
    n_rows = math.ceil(n_tiles / n_cols)

    tile_width = width / n_cols
    tile_height = height / n_rows
    col_indices = np.arange(n_cols)
    row_indices = np.arange(n_rows)

    tile_minx_arr = minx + col_indices * tile_width
    tile_maxx_arr = np.minimum(minx + (col_indices + 1) * tile_width, maxx)
    tile_miny_arr = miny + row_indices * tile_height
    tile_maxy_arr = np.minimum(miny + (row_indices + 1) * tile_height, maxy)

    tile_minx_grid, tile_miny_grid = np.meshgrid(tile_minx_arr, tile_miny_arr)
    tile_maxx_grid, tile_maxy_grid = np.meshgrid(tile_maxx_arr, tile_maxy_arr)

    tiles = list(zip(
        tile_minx_grid.flatten(),
        tile_miny_grid.flatten(),
        tile_maxx_grid.flatten(),
        tile_maxy_grid.flatten()
    ))

    session = requests.Session()
    session.headers.update({
        "X-Api-Key": resolved_key,
        "Accept": "application/hal+json",
        "Accept-Crs": "epsg:28992",
        "Content-Crs": "epsg:28992"
    })

    def fetch_tile(tile_coords):
        """Fetch buildings for a single tile with error handling."""
        tile_minx, tile_miny, tile_maxx, tile_maxy = tile_coords
        bbox_rd = f"{tile_minx},{tile_miny},{tile_maxx},{tile_maxy}"
        buildings = []
        page = 1
        
        while True:
            params = {"bbox": bbox_rd, "page": page, "pageSize": 100}
            
            try:
                response = session.get(base_url, params=params, timeout=30)
            except requests.exceptions.Timeout:
                logger.warning(f"Request timeout for tile {bbox_rd}, page {page}")
                raise BAGAPIError(f"Request timeout for tile {bbox_rd}", status_code=None)
            except requests.exceptions.ConnectionError as e:
                logger.warning(f"Connection error for tile {bbox_rd}: {e}")
                raise BAGAPIError(f"Connection error: {e}", status_code=None)
            
            # Handle specific HTTP status codes
            if response.status_code == 401:
                raise BAGAPIError(
                    "Authentication failed. Check your BAG API key.",
                    status_code=401,
                    response_text=response.text
                )
            elif response.status_code == 403:
                raise BAGAPIError(
                    "Access forbidden. API key may lack required permissions.",
                    status_code=403,
                    response_text=response.text
                )
            elif response.status_code == 429:
                raise BAGAPIError(
                    "Rate limit exceeded. Please wait before retrying.",
                    status_code=429,
                    response_text=response.text
                )
            elif response.status_code >= 500:
                raise BAGAPIError(
                    f"BAG API server error (HTTP {response.status_code})",
                    status_code=response.status_code,
                    response_text=response.text
                )
            elif response.status_code != 200:
                logger.warning(
                    f"Unexpected status {response.status_code} for tile {bbox_rd}: "
                    f"{response.text[:200]}"
                )
                break
            
            data = response.json()
            if '_embedded' in data and 'panden' in data['_embedded']:
                page_buildings = data['_embedded']['panden']
                buildings.extend(page_buildings)
                if len(page_buildings) < 100:
                    break
                page += 1
            else:
                break
                
        return buildings

    all_buildings = []
    errors = []
    
    with ThreadPoolExecutor(max_workers=2) as executor:
        future_to_tile = {executor.submit(fetch_tile, tile): i for i, tile in enumerate(tiles)}
        for future in as_completed(future_to_tile):
            tile_idx = future_to_tile[future]
            try:
                buildings = future.result()
                all_buildings.extend(buildings)
            except BAGAPIError as e:
                errors.append((tile_idx, e))
                # Re-raise critical errors immediately
                if e.status_code in (401, 403, 429):
                    raise
    
    # Log any non-critical errors that occurred
    if errors:
        logger.warning(f"{len(errors)} tile(s) failed to fetch: {[e[1] for e in errors]}")

    return all_buildings


def load_buildings_from_cache(bounding_box, cache_path='inputs/bag_cache'):
    """
    Loads building and address data from cached pickle files and filters to bounding box.
    
    Parameters
    ----------
    bounding_box : list
        [min_lon, min_lat, max_lon, max_lat] in WGS84.
    cache_path : str
        Path to directory containing cached pickle files.
    
    Returns
    -------
    tuple
        (all_buildings, building_addresses) - filtered to bounding box
    
    Raises
    ------
    FileNotFoundError
        If cache files do not exist.
    """
    
    buildings_file = os.path.join(cache_path, 'delft_all_buildings.pkl')
    addresses_file = os.path.join(cache_path, 'delft_building_addresses.pkl')
    
    if not os.path.exists(buildings_file) or not os.path.exists(addresses_file):
        raise FileNotFoundError(
            f"BAG cache files not found in {cache_path}/\n"
            f"Required files: delft_all_buildings.pkl, delft_building_addresses.pkl\n"
            f"Please run cache_bag_data.ipynb to create cache files."
        )
    
    # Load full cache
    with open(buildings_file, 'rb') as f:
        all_buildings_full = pickle.load(f)
    
    with open(addresses_file, 'rb') as f:
        building_addresses_full = pickle.load(f)
    
    # Convert bounding box to RD New coordinates for filtering
    min_lon, min_lat, max_lon, max_lat = bounding_box
    transformer = Transformer.from_crs("EPSG:4326", "EPSG:28992", always_xy=True)
    min_x, min_y = transformer.transform(min_lon, min_lat)
    max_x, max_y = transformer.transform(max_lon, max_lat)
    
    # Filter buildings by bounding box
    all_buildings = []
    for building in all_buildings_full:
        if 'pand' in building and isinstance(building['pand'], dict):
            pand_data = building['pand']
            if 'geometrie' in pand_data and 'coordinates' in pand_data['geometrie']:
                coords = pand_data['geometrie']['coordinates'][0]
                # Check if centroid is within bounding box
                centroid_x = sum(c[0] for c in coords) / len(coords)
                centroid_y = sum(c[1] for c in coords) / len(coords)
                
                if min_x <= centroid_x <= max_x and min_y <= centroid_y <= max_y:
                    all_buildings.append(building)
    
    # Filter addresses to match filtered buildings
    building_ids = set()
    for building in all_buildings:
        if 'pand' in building and isinstance(building['pand'], dict):
            pand_id = building['pand'].get('identificatie')
        elif 'identificatie' in building:
            pand_id = building.get('identificatie')
        else:
            continue
        if pand_id:
            building_ids.add(pand_id)
    
    building_addresses = {k: v for k, v in building_addresses_full.items() if k in building_ids}
    
    return all_buildings, building_addresses
