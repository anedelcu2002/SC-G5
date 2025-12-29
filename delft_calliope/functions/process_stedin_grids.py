import geopandas as gpd
import folium
from shapely.geometry import Polygon
from shapely.ops import snap

def process_stedin_grids(
    bbox_coords,
    features_to_remove_heat,
    features_to_remove_elec,
    mode='plot',
    heat_grid_path="inputs/stedin_delft_gas_grid.geojson",
    elec_grid_path="inputs/stedin_delft_elec_grid.geojson",
    simplify_tolerance=0.000001,
    snap_tolerance=0.000001
):
    """
    Loads, filters, and cleans Stedin heat and electricity grid data.
    
    Args:
        bbox_coords (list of tuples): Polygon coordinates defining the area of interest.
        features_to_remove_heat (list of str): Heat/gas network feature names to exclude.
        features_to_remove_elec (list of str): Electricity network feature names to exclude.
        mode (str): If 'plot', creates interactive map visualizations. Default is 'plot'.
        heat_grid_path (str): Path to heat/gas grid GeoJSON file.
        elec_grid_path (str): Path to electricity grid GeoJSON file.
        simplify_tolerance (float): Geometry simplification precision (in degrees).
        snap_tolerance (float): Geometry snapping threshold (in degrees).
    
    Returns:
        tuple: (stedin_heat_gdf_delft, stedin_elec_gdf_delft)
            - stedin_heat_gdf_delft: Cleaned heat/gas network GeoDataFrame
            - stedin_elec_gdf_delft: Cleaned electricity network GeoDataFrame
    """
    
    # --- Load and filter Stedin grid data ---
    
    # Read the shapefiles into GeoDataFrames
    stedin_heat_gdf = gpd.read_file(heat_grid_path)
    stedin_elec_gdf = gpd.read_file(elec_grid_path)

    # Reproject to WGS84 if needed
    if stedin_heat_gdf.crs and stedin_heat_gdf.crs.to_epsg() != 4326:
        stedin_heat_gdf = stedin_heat_gdf.to_crs(epsg=4326)

    if stedin_elec_gdf.crs and stedin_elec_gdf.crs.to_epsg() != 4326:
        stedin_elec_gdf = stedin_elec_gdf.to_crs(epsg=4326)

    # Create the polygon for area of interest
    polygon = Polygon(bbox_coords)
    polygon_gdf = gpd.GeoDataFrame(index=[0], crs="EPSG:4326", geometry=[polygon])

    # Filter geometries that intersect the polygon
    stedin_heat_gdf_delft = stedin_heat_gdf[stedin_heat_gdf.geometry.intersects(polygon)]
    stedin_heat_gdf_delft = stedin_heat_gdf_delft.reset_index(drop=True)
    stedin_heat_gdf_delft['feature_name'] = [f"heat_feature{i}" for i in range(len(stedin_heat_gdf_delft))]

    stedin_elec_gdf_delft = stedin_elec_gdf[stedin_elec_gdf.geometry.intersects(polygon)].reset_index(drop=True)
    stedin_elec_gdf_delft['feature_name'] = [f"elec_feature{i}" for i in range(len(stedin_elec_gdf_delft))]

    # --- Remove disconnected features ---
    
    # Filter out unwanted features
    stedin_heat_gdf_delft = stedin_heat_gdf_delft[~stedin_heat_gdf_delft['feature_name'].isin(features_to_remove_heat)].reset_index(drop=True).copy()
    stedin_elec_gdf_delft = stedin_elec_gdf_delft[~stedin_elec_gdf_delft['feature_name'].isin(features_to_remove_elec)].reset_index(drop=True).copy()

    # --- Clean up electricity grid topology ---
    
    # Simplify all geometries
    stedin_elec_gdf_delft['geometry'] = stedin_elec_gdf_delft['geometry'].apply(
        lambda geom: geom.simplify(simplify_tolerance, preserve_topology=True)
    )

    # Snap all features together
    all_geoms = list(stedin_elec_gdf_delft.geometry)
    snapped_geoms = []
    for i, geom in enumerate(all_geoms):
        snapped = geom
        for j, other in enumerate(all_geoms):
            if i != j:
                snapped = snap(snapped, other, snap_tolerance)
        snapped_geoms.append(snapped)

    stedin_elec_gdf_delft['geometry'] = snapped_geoms

    # --- Visualization (optional) ---
    
    if mode == 'plot':
        # Project to local CRS for accurate centroid calculation (use heat network for centering)
        stedin_heat_gdf_delft_proj = stedin_heat_gdf_delft.to_crs(epsg=28992)
        centroids_proj = stedin_heat_gdf_delft_proj.geometry.centroid
        centroids_wgs = centroids_proj.to_crs(epsg=4326)
        center = [centroids_wgs.y.mean(), centroids_wgs.x.mean()]

        # Create the map
        stedin_map = folium.Map(location=center, zoom_start=13, tiles="OpenStreetMap")

        # Create FeatureGroups for each network
        heat_group = folium.FeatureGroup(name="Gas (Heat) Network", show=True)
        elec_group = folium.FeatureGroup(name="Electricity Network", show=True)
        # Add each heat feature
        for _, row in stedin_heat_gdf_delft.iterrows():
            folium.GeoJson(
                row.geometry,
                name=row['feature_name'],
                popup=folium.Popup(row['feature_name'], parse_html=True),
                style_function=lambda x: {'color': '#ff5100'}
            ).add_to(heat_group)

        # Add each electricity feature
        for _, row in stedin_elec_gdf_delft.iterrows():
            folium.GeoJson(
                row.geometry,
                name=row['feature_name'],
                popup=folium.Popup(row['feature_name'], parse_html=True),
                style_function=lambda x: {'color': '#3186cc'}
            ).add_to(elec_group)

        # Add groups to map
        heat_group.add_to(stedin_map)
        elec_group.add_to(stedin_map)

        # Add layer control for toggling
        folium.LayerControl().add_to(stedin_map)

        stedin_map.save("debug/stedin_map.html")
    
    return stedin_heat_gdf_delft, stedin_elec_gdf_delft
