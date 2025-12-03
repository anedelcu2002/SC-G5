import requests
import numpy as np
import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from pyproj import Transformer

def fetch_buildings_from_BAG(bounding_box, BAG_API_KEY):
    """
    Fetches building data from the BAG API using spatial tiling and parallel requests.

    Args:
        bounding_box (list): [min_lon, min_lat, max_lon, max_lat] in WGS84.
        BAG_API_KEY (str): API key for BAG Individuele Bevragingen.

    Returns:
        list: all_buildings, a list of building dicts from the BAG API.
    """
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
        "X-Api-Key": BAG_API_KEY,
        "Accept": "application/hal+json",
        "Accept-Crs": "epsg:28992",
        "Content-Crs": "epsg:28992"
    })

    def fetch_tile(tile_coords):
        tile_minx, tile_miny, tile_maxx, tile_maxy = tile_coords
        bbox_rd = f"{tile_minx},{tile_miny},{tile_maxx},{tile_maxy}"
        buildings = []
        page = 1
        while True:
            params = {"bbox": bbox_rd, "page": page, "pageSize": 100}
            response = session.get(base_url, params=params)
            if response.status_code != 200:
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
    with ThreadPoolExecutor(max_workers=4) as executor:
        future_to_tile = {executor.submit(fetch_tile, tile): i for i, tile in enumerate(tiles)}
        for future in as_completed(future_to_tile):
            buildings = future.result()
            all_buildings.extend(buildings)

    return all_buildings