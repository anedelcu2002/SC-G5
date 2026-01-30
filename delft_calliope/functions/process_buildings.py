import pandas as pd
import geopandas as gpd
import folium
from shapely.geometry import Polygon

def process_and_visualize_buildings(all_buildings, building_addresses, mode='plot', debug_folder='debug'):
    """
    Creates a building DataFrame from BAG API data and optionally visualizes it.
    
    Args:
        all_buildings (list): List of building dictionaries from BAG API.
        building_addresses (dict): Dictionary mapping building IDs to address information.
        mode (str): If 'plot', creates an interactive map visualization. Default is 'plot'.
        debug_folder (str): Folder for debug visualizations (default: 'debug').
    
    Returns:
        pd.DataFrame: DataFrame containing building information with geometry, addresses, and metadata.
    """
    # Merge addresses into buildings data structure with consolidated format
    for building in all_buildings:
        # Extract building ID using same nested logic
        pand_id = None
        if 'pand' in building and isinstance(building['pand'], dict):
            pand_id = building['pand'].get('identificatie')
        elif 'identificatie' in building:
            pand_id = building.get('identificatie')

        # Get address info from building_addresses
        addr_info = building_addresses.get(pand_id, {'address': '', 'aantal_adressen': 0})
        building['address'] = addr_info['address']
        building['aantal_adressen'] = addr_info['aantal_adressen']

    buildings_data = []

    for building in all_buildings:
        # Skip buildings without addresses
        if building.get('aantal_adressen', 0) == 0:
            continue
        
        if 'pand' in building and isinstance(building['pand'], dict):
            pand_data = building['pand']
            
            # Extract geometry coordinates (first point of polygon for representative location)
            geometry_coords = None
            if 'geometrie' in pand_data and 'coordinates' in pand_data['geometrie']:
                geom_data = pand_data['geometrie']
                if geom_data['type'] == 'Polygon':
                    # Get centroid of first coordinate ring
                    coords = geom_data['coordinates'][0]
                    lon = sum(c[0] for c in coords) / len(coords)
                    lat = sum(c[1] for c in coords) / len(coords)
                    geometry_coords = (lon, lat)
            
            buildings_data.append({
                'id': pand_data.get('identificatie', ''),
                'addresses': building.get('address', ''),
                'nr_addresses': building.get('aantal_adressen', 0),
                'year_construction': pand_data.get('oorspronkelijkBouwjaar', ''),
                'geometry': Polygon(pand_data.get('geometrie', {}).get('coordinates', '')[0]),
                'lon': geometry_coords[0],
                'lat': geometry_coords[1]
            })

    # Create DataFrame
    buildings_df = pd.DataFrame(buildings_data)
    buildings_df = buildings_df.drop_duplicates(subset=['id']).reset_index(drop=True)
    
    # Visualization (only if mode is 'plot')
    if mode == 'plot':
        # Ensure buildings_gdf is a GeoDataFrame in RD New
        if not isinstance(buildings_df, gpd.GeoDataFrame):
            buildings_gdf = gpd.GeoDataFrame(buildings_df, geometry='geometry', crs='EPSG:28992')
        else:
            buildings_gdf = buildings_df

        # Convert to WGS84 for mapping
        buildings_gdf_wgs84 = buildings_gdf.to_crs(epsg=4326)

        # Calculate centroids in projected CRS (RD New)
        centroids_projected = buildings_gdf.geometry.centroid

        # Convert centroids to WGS84
        centroids_wgs84 = centroids_projected.to_crs(epsg=4326)

        # Use these for map center
        center_lat = centroids_wgs84.y.mean()
        center_lon = centroids_wgs84.x.mean()

        # Create Folium map
        buildings_map = folium.Map(
            location=[center_lat, center_lon],
            zoom_start=16,
            tiles="OpenStreetMap"
        )

        # Add building polygons with popups
        for idx, row in buildings_gdf_wgs84.iterrows():
            color = '#3186cc' if row['nr_addresses'] > 0 else '#cccccc'
            fill_opacity = 0.6 if row['nr_addresses'] > 0 else 0.3

            # Use centroid of geometry for lon/lat in popup
            centroid = row.geometry.centroid
            popup_html = f"""
            <div style="font-family: Arial, sans-serif; width: 250px;">
                <b style="font-size: 14px;">Address:</b><br>
                <span style="font-size: 13px; color: #2e86ab;">{row['addresses']}</span><br><br>
                <b>Building ID:</b> {row['id']}<br>
                <b>Number of addresses:</b> {row['nr_addresses']}<br>
                <b>Construction year:</b> {row['year_construction']}<br>
                <b>Centroid (lon, lat):</b> {centroid.x:.5f}, {centroid.y:.5f}
            </div>
            """

            folium.GeoJson(
                row.geometry,
                style_function=lambda x, color=color, fill_opacity=fill_opacity: {
                    'fillColor': color,
                    'color': color,
                    'weight': 2,
                    'fillOpacity': fill_opacity
                },
                popup=folium.Popup(popup_html, max_width=300)
            ).add_to(buildings_map)

        # Add statistics to map
        total_buildings = len(buildings_gdf_wgs84)
        buildings_with_addr = len(buildings_gdf_wgs84[buildings_gdf_wgs84['nr_addresses'] > 0])

        legend_html = f"""
        <div style="position: fixed; bottom: 50px; left: 50px; width: 220px; height: 110px; 
                    background-color: white; border:2px solid grey; z-index:9999; 
                    font-size:14px; padding: 10px">
            <b>Building Statistics</b><br>
            Total buildings: {total_buildings}<br>
            With addresses: {buildings_with_addr}<br>
            Without addresses: {total_buildings - buildings_with_addr}<br><br>
            <span style="color: #3186cc;">■</span> Has address<br>
            <span style="color: #cccccc;">■</span> No address
        </div>
        """
        buildings_map.get_root().html.add_child(folium.Element(legend_html))

        # Save map
        import os
        os.makedirs(debug_folder, exist_ok=True)
        buildings_map.save(os.path.join(debug_folder, "buildings_addresses_map.html"))
    
    return buildings_df
