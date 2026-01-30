import pandas as pd
import geopandas as gpd
import folium
from pyproj import Transformer
from shapely import area
from functions.TNO_API import fetch_residential_heat_demand

def process_heat_demand(buildings_df, area, year, mode='plot', online=True, csv_path='inputs/heat_demand_cache', debug_folder='debug'):
    """
    Fetches residential heat demand data, merges it with building data, and optionally visualizes it.
    
    Args:
        buildings_df (pd.DataFrame): DataFrame containing building information with geometry and coordinates.
        area (str): Area code for fetching heat demand data (e.g., '4341' for Mythologiebuurt 2020).
        year (int): Year for fetching heat demand data (used only for online API calls).
        debug_folder (str): Folder for debug visualizations (default: 'debug').
        mode (str): If 'plot', creates an interactive heat demand map visualization. Default is 'plot'.
        online (bool): If True, fetch from TNO API; if False, load from CSV file. Default is True.
        csv_path (str): Path to directory containing CSV cache files. Default is 'inputs/heat_demand_cache'.
    
    Returns:
        tuple: (merged_df, buildings_gdf)
            - merged_df: DataFrame with buildings and their heat demand data
            - buildings_gdf: GeoDataFrame with geometry for further processing
    """
    # Fetch residential heat demand data (online or offline)
    residential_heat_demand = fetch_residential_heat_demand(area, year, online=online, csv_path=csv_path)

    # Ensure IDs are strings and properly formatted (add leading zero if needed)
    if 'id' in residential_heat_demand.columns:
        residential_heat_demand['id'] = residential_heat_demand['id'].astype(str)
        # Add leading zero if ID is 15 digits (BAG IDs are 16 digits)
        residential_heat_demand['id'] = residential_heat_demand['id'].apply(
            lambda x: f'0{x}' if len(x) == 15 else x
        )

    gdf = buildings_df.copy()
    
    gdf = buildings_df.copy()
    transformer = Transformer.from_crs("EPSG:28992", "EPSG:4326", always_xy=True)

    # Apply transformation to each row
    gdf[['lon', 'lat']] = gdf.apply(
        lambda row: pd.Series(transformer.transform(row['lon'], row['lat'])),
        axis=1
    )

    # Prepare export DataFrame with identification and coordinates
    export_cols = ['id', 'lon', 'lat', 'geometry', 'addresses', 'nr_addresses', 'year_construction']
    export_df = gdf[export_cols].copy() if all(col in gdf.columns for col in export_cols) else gdf[[c for c in export_cols if c in gdf.columns]].copy()
    export_df = export_df.rename(columns={'id': 'id'})

    # Filter export_df to only include ids present in residential_heat_demand
    valid_ids = set(residential_heat_demand['id'])
    export_df_filtered = export_df[export_df['id'].isin(valid_ids)].copy()

    # Merge heat demand with building data
    merged_df = pd.merge(residential_heat_demand, export_df_filtered, on='id', how='inner')
    merged_df.drop_duplicates(subset=['id'], inplace=True)

    # Create GeoDataFrame with building polygons (preserving geometry)
    buildings_gdf = pd.merge(
        residential_heat_demand, 
        merged_df[['id', 'geometry']], 
        on='id', 
        how='inner'
    )
    buildings_gdf = gpd.GeoDataFrame(buildings_gdf, geometry='geometry', crs='EPSG:28992')

    # Visualize buildings on Folium map (only if mode is 'plot')
    if mode == 'plot':
        # Convert to WGS84 for mapping
        buildings_gdf_wgs84 = buildings_gdf.to_crs(epsg=4326)
        
        # Calculate map center from building centroids (in projected CRS to avoid warnings)
        buildings_gdf_projected = buildings_gdf.to_crs(epsg=28992)  # Project to accurate CRS
        centroids_projected = buildings_gdf_projected.geometry.centroid
        centroids_wgs84 = centroids_projected.to_crs(epsg=4326)  # Convert back to WGS84
        center_lat = centroids_wgs84.y.mean()
        center_lon = centroids_wgs84.x.mean()
        
        # Create Folium map
        buildings_map = folium.Map(location=[center_lat, center_lon], zoom_start=15, tiles="OpenStreetMap")
        
        # Add building polygons with color based on heat demand
        # Normalize heat demand for color scale
        max_demand = buildings_gdf['Peak heat demand (kW)'].max()
        min_demand = buildings_gdf['Peak heat demand (kW)'].min()
        
        for idx, row in buildings_gdf_wgs84.iterrows():
            # Calculate color intensity based on heat demand (red = high demand)
            demand = row['Peak heat demand (kW)']
            normalized = (demand - min_demand) / (max_demand - min_demand) if max_demand > min_demand else 0.5
            
            # Color from light yellow (low demand) to dark red (high demand)
            red = int(255)
            green = int(255 * (1 - normalized * 0.8))  # Reduces green as demand increases
            blue = int(255 * (1 - normalized))  # Reduces blue as demand increases
            color = f'#{red:02x}{green:02x}{blue:02x}'
            
            folium.GeoJson(
                row.geometry,
                style_function=lambda x, color=color: {
                    'fillColor': color,
                    'color': '#333333',
                    'weight': 1,
                    'fillOpacity': 0.8
                },
                popup=folium.Popup(
                    f"<b>Building ID:</b> {row['id']}<br>"
                    f"<b>Peak Heat Demand:</b> {row['Peak heat demand (kW)']:.2f} kW<br>",
                    max_width=250
                )
            ).add_to(buildings_map)
        
        # Save map
        import os
        os.makedirs(debug_folder, exist_ok=True)
        buildings_map.save(os.path.join(debug_folder, "buildings_heat_demand_map.html"))
    
    return merged_df, buildings_gdf
