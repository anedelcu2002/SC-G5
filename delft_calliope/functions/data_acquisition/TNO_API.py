"""
TNO Heat Demand API Interface

This module fetches residential heat demand data from the TNO Warmteprofielengenerator
(Heat Profile Generator) API, with support for offline caching via CSV files.

API Documentation:
    The TNO Warmteprofielengenerator provides heat demand profiles for Dutch buildings.
    - Building data endpoint: Returns GeoJSON with building energy characteristics
    - Heat profile endpoint: Returns hourly heat demand time series via InfluxDB/Grafana
    
Note:
    The API endpoints are publicly accessible and do not require authentication.
    However, they may be subject to rate limiting or availability changes.
"""

import pandas as pd
import requests
import logging
import os
from datetime import datetime


# Configure module logger
logger = logging.getLogger(__name__)


# =============================================================================
# API CONFIGURATION
# =============================================================================
# These URLs point to TNO's public Warmteprofielengenerator service.
# If the service is moved or updated, only these constants need to change.

TNO_BUILDING_API_BASE = "https://hlc-api.warmteprofielengenerator.nl"
TNO_GRAFANA_API_BASE = "https://hlc-grafana.warmteprofielengenerator.nl"

# Minimal headers required for API requests
# User-Agent and Origin are needed for CORS compliance
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json",
    "Origin": "https://www.warmteprofielengenerator.nl"
}


class TNOAPIError(Exception):
    """Exception raised for TNO API errors."""
    
    def __init__(self, message, status_code=None, endpoint=None):
        self.status_code = status_code
        self.endpoint = endpoint
        super().__init__(message)


def fetch_residential_heat_demand(area, year, online=True, csv_path='inputs/heat_demand_cache'):
    """
    Fetch residential heat demand data either from TNO API (online) or from CSV cache (offline).
    
    Parameters
    ----------
    area : str
        Area code for the neighborhood (e.g., '4315', '4341').
    year : int
        Year for fetching heat demand data (e.g., 2019, 2020).
    online : bool, optional
        If True, fetch from TNO API; if False, load from CSV file. Default is True.
    csv_path : str, optional
        Path to directory containing CSV cache files. Default is 'inputs/heat_demand_cache'.
    
    Returns
    -------
    pd.DataFrame
        DataFrame with columns ['id', 'Warmtevraag', 'share', 'Peak heat demand (kW)']
    
    Raises
    ------
    FileNotFoundError
        If offline mode and CSV cache file does not exist.
    TNOAPIError
        If online mode and API request fails.
    ValueError
        If CSV file is missing required columns.
    """
    
    if not online:
        return _load_from_cache(area, csv_path)
    
    return _fetch_from_api(area, year)


def _load_from_cache(area, csv_path):
    """Load heat demand data from CSV cache."""
    csv_file = os.path.join(csv_path, f"{area}.csv")
    
    if not os.path.exists(csv_file):
        raise FileNotFoundError(
            f"Heat demand CSV file not found: {csv_file}\n"
            f"Please ensure the file exists or set online=True to fetch from API."
        )
    
    try:
        df_full = pd.read_csv(csv_file)
    except Exception as e:
        raise ValueError(f"Error reading CSV file {csv_file}: {e}")
    
    # Verify required columns exist
    required_columns = ['id', 'Warmtevraag', 'share', 'Peak heat demand (kW)']
    missing_columns = [col for col in required_columns if col not in df_full.columns]
    
    if missing_columns:
        raise ValueError(
            f"CSV file missing required columns: {missing_columns}\n"
            f"Required columns: {required_columns}\n"
            f"Found columns: {list(df_full.columns)}"
        )
    
    # Select only the required columns
    building_heat_demand = df_full[required_columns].copy()
    logger.info(f"Loaded {len(building_heat_demand)} buildings from cache: {csv_file}")
    
    return building_heat_demand


def _fetch_from_api(area, year):
    """Fetch heat demand data from TNO API."""
    logger.info(f"Fetching heat demand data from TNO API for area {area}, year {year}...")
    
    # Step 1: Fetch building GeoJSON data
    geojson_url = f"{TNO_BUILDING_API_BASE}/building_data/geojson/{area}"
    
    try:
        response = requests.get(geojson_url, headers=DEFAULT_HEADERS, timeout=30)
    except requests.exceptions.Timeout:
        raise TNOAPIError(
            f"Timeout fetching building data for area {area}",
            endpoint=geojson_url
        )
    except requests.exceptions.ConnectionError as e:
        raise TNOAPIError(
            f"Connection error fetching building data: {e}",
            endpoint=geojson_url
        )
    
    if response.status_code != 200:
        raise TNOAPIError(
            f"Failed to fetch building data (HTTP {response.status_code}): {response.text[:200]}",
            status_code=response.status_code,
            endpoint=geojson_url
        )
    
    building_data = response.json()
    
    if "features" not in building_data or len(building_data["features"]) == 0:
        logger.warning(f"No building features found for area {area}")
        return pd.DataFrame()
    
    properties_list = [f.get("properties", {}) for f in building_data["features"]]
    residential_heat_demand = pd.DataFrame(properties_list)
    
    # Step 2: Fetch heat demand time series
    start_date = datetime(year, 1, 1)
    start_timestamp = int(start_date.timestamp() * 1000)
    
    end_date = datetime(year, 12, 31, 23, 59, 59)
    end_timestamp = int(end_date.timestamp() * 1000)
    
    query = (
        f"SELECT sum(\"P_heat\") FROM \"tot-{area}\" "
        f"WHERE time >= {start_timestamp}ms and time <= {end_timestamp}ms "
        f"GROUP BY time(1h) fill(null)"
    )
    
    grafana_url = (
        f"{TNO_GRAFANA_API_BASE}/api/datasources/proxy/2/query"
        f"?db=tnohlc&q={requests.utils.quote(query)}&epoch=ms"
    )
    
    # Grafana requires additional headers for the proxy endpoint
    grafana_headers = {
        **DEFAULT_HEADERS,
        "Referer": f"{TNO_GRAFANA_API_BASE}/",
        "x-grafana-org-id": "1"
    }
    
    try:
        response = requests.get(grafana_url, headers=grafana_headers, timeout=60)
    except requests.exceptions.Timeout:
        raise TNOAPIError(
            f"Timeout fetching heat profiles for area {area}, year {year}",
            endpoint="grafana_proxy"
        )
    except requests.exceptions.ConnectionError as e:
        raise TNOAPIError(
            f"Connection error fetching heat profiles: {e}",
            endpoint="grafana_proxy"
        )
    
    if response.status_code != 200:
        raise TNOAPIError(
            f"Failed to fetch heat profiles (HTTP {response.status_code}): {response.text[:200]}",
            status_code=response.status_code,
            endpoint="grafana_proxy"
        )
    
    data = response.json()
    
    # Extract the heat demand series
    series = data.get("results", [])[0].get("series", []) if "results" in data else []
    heat_df = None
    
    for s in series:
        name = s.get("name", "")
        if name == f"tot-{area}":
            columns = s.get("columns", [])
            values = s.get("values", [])
            heat_df = pd.DataFrame(values, columns=columns)
            break
    
    if heat_df is None:
        logger.warning(f"No heat demand series found for area {area}")
        return pd.DataFrame()
    
    # Step 3: Calculate building peak heat demand
    building_heat_demand = residential_heat_demand[["id", "Warmtevraag"]].copy()
    warmtevraag_sum = building_heat_demand["Warmtevraag"].sum()
    
    if warmtevraag_sum == 0:
        logger.warning(f"Total heat demand is zero for area {area}")
        building_heat_demand["share"] = 0
        building_heat_demand["Peak heat demand (kW)"] = 0
    else:
        building_heat_demand["share"] = building_heat_demand["Warmtevraag"] / warmtevraag_sum
        max_heat = heat_df["sum"].max()
        building_heat_demand["Peak heat demand (kW)"] = building_heat_demand["share"] * max_heat / 1000
    
    logger.info(f"Heat demand data fetched successfully from API ({len(building_heat_demand)} buildings)")
    return building_heat_demand


if __name__ == "__main__":
    # Test the API
    logging.basicConfig(level=logging.INFO)
    df = fetch_residential_heat_demand("4011", 2019)
    print(df.head())
