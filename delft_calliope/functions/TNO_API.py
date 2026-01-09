import pandas as pd
import requests
from datetime import datetime

def fetch_residential_heat_demand(area, year):
    # Fetch building GeoJSON energy consumption data for the given area
    geojson_url = f"https://hlc-api.warmteprofielengenerator.nl/building_data/geojson/{area}"
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
        "Referer": "https://www.warmteprofielengenerator.nl/",
        "Origin": "https://www.warmteprofielengenerator.nl"
    }
    response = requests.get(geojson_url, headers=headers)
    response.raise_for_status()
    building_data = response.json()
    if "features" in building_data and len(building_data["features"]) > 0:
        properties_list = [f.get("properties", {}) for f in building_data["features"]]
        residential_heat_demand = pd.DataFrame(properties_list)
    else:
        print("No features to export.")
        return pd.DataFrame()
    
    # Calculate timestamps for the given year
    # Start: January 1 of the year at 00:00:00 UTC
    start_date = datetime(year, 1, 1)
    start_timestamp = int(start_date.timestamp() * 1000)  # Convert to milliseconds
    
    # End: December 31 of the year at 23:59:59 UTC
    end_date = datetime(year, 12, 31, 23, 59, 59)
    end_timestamp = int(end_date.timestamp() * 1000)  # Convert to milliseconds
    
    # Fetch heat demand data from the InfluxDB/Grafana API
    query = (
        f"SELECT sum(\"P_heat\") FROM \"tot-{area}\" "
        f"WHERE time >= {start_timestamp}ms and time <= {end_timestamp}ms GROUP BY time(1h) fill(null)"
    )
    url = (
        "https://hlc-grafana.warmteprofielengenerator.nl/api/datasources/proxy/2/query?db=tnohlc"
        f"&q={requests.utils.quote(query)}"
        "&epoch=ms"
    )
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:145.0) Gecko/20100101 Firefox/145.0",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Referer": f"https://hlc-grafana.warmteprofielengenerator.nl/d-solo/BJBoKWivz/warmtevraagprofiel-{year}-{area}?orgId=1&panelId=1&from={start_timestamp}&to={end_timestamp}&theme=light",
        "x-grafana-org-id": "1",
        "DNT": "1",
        "Connection": "keep-alive",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
        "Priority": "u=4",
        "TE": "trailers"
    }
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    data = response.json()

    # Extract the heat demand series only
    series = data.get("results", [])[0].get("series", []) if "results" in data else []
    heat_df = None
    for s in series:
        name = s.get("name", "")
        columns = s.get("columns", [])
        values = s.get("values", [])
        if name == f"tot-{area}":
            heat_df = pd.DataFrame(values, columns=columns)

    # Calculate building peak heat demand
    if (residential_heat_demand is not None) and (heat_df is not None):
        building_heat_demand = residential_heat_demand[["id", "Warmtevraag"]].copy()
        warmtevraag_sum = building_heat_demand["Warmtevraag"].sum()
        # Calculate share for each building
        building_heat_demand["share"] = building_heat_demand["Warmtevraag"] / warmtevraag_sum
        # Get max hourly heat demand from heat_df
        max_heat = heat_df["sum"].max()
        # Multiply share by max_heat
        building_heat_demand["Peak heat demand (kW)"] = building_heat_demand["share"] * max_heat/1000
        #print("Residential heat demand data fetched and calculated successfully.")
        return building_heat_demand
    else:
        print("Data not available for calculation.")
        return pd.DataFrame()

if __name__ == "__main__":
    df = fetch_residential_heat_demand("4011", 2019)