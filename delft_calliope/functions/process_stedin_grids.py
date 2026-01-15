import geopandas as gpd
import folium
import requests
from shapely.geometry import Polygon
from shapely.ops import snap
from pyproj import Transformer
import pickle
import os
from functions.process_osm_roads import extract_osm_roads


def fetch_stedin_layer_from_arcgis(bbox_coords, layer_url, layer_name="Layer", max_records=2000):
    """
    Fetches features from an ArcGIS REST Feature Service layer within a bounding box.
    Handles pagination to retrieve all features (not limited to 2000).
    
    Args:
        bbox_coords (list of tuples): Polygon coordinates [(lon, lat), ...] in WGS84
        layer_url (str): ArcGIS Feature Service layer URL 
        layer_name (str): Descriptive name for logging
        max_records (int): Maximum records per request (ArcGIS limit is usually 2000)
    
    Returns:
        GeoDataFrame: Spatial features from the service in EPSG:4326
    """
    # Extract bounding box envelope in WGS84
    lons = [coord[0] for coord in bbox_coords]
    lats = [coord[1] for coord in bbox_coords]
    xmin_wgs, xmax_wgs = min(lons), max(lons)
    ymin_wgs, ymax_wgs = min(lats), max(lats)
    
    # Transform to EPSG:28992 (Dutch RD coordinate system that Stedin uses)
    transformer = Transformer.from_crs("EPSG:4326", "EPSG:28992", always_xy=True)
    xmin_rd, ymin_rd = transformer.transform(xmin_wgs, ymin_wgs)
    xmax_rd, ymax_rd = transformer.transform(xmax_wgs, ymax_wgs)
    
    # Build query parameters for ArcGIS REST API
    base_params = {
        'where': '1=1',  # Get all features
        'geometry': f'{xmin_rd},{ymin_rd},{xmax_rd},{ymax_rd}',
        'geometryType': 'esriGeometryEnvelope',
        'inSR': '28992',  # Input spatial reference (Dutch RD)
        'spatialRel': 'esriSpatialRelIntersects',
        'outFields': '*',  # Get all attributes
        'returnGeometry': 'true',
        'f': 'geojson',  # Return as GeoJSON
        'outSR': '4326',  # Output as WGS84 for compatibility
        'resultRecordCount': max_records
    }
    
    # Make request to /query endpoint
    query_url = f"{layer_url}/query"
    
    #print(f"Fetching {layer_name} from Stedin ArcGIS service...")
    
    all_features = []
    offset = 0
    
    try:
        while True:
            # Add offset parameter for pagination
            params = base_params.copy()
            if offset > 0:
                params['resultOffset'] = offset
            
            response = requests.get(query_url, params=params, timeout=30)
            response.raise_for_status()
            
            # Parse GeoJSON response
            geojson_data = response.json()
            
            # Check if we got any features
            if 'features' in geojson_data and len(geojson_data['features']) > 0:
                features_count = len(geojson_data['features'])
                all_features.extend(geojson_data['features'])
                #print(f"  Fetched {features_count} features (total so far: {len(all_features)})")
                
                # Check if we got fewer features than max_records, meaning we're done
                if features_count < max_records:
                    break
                
                # Otherwise, increment offset and continue
                offset += features_count
            else:
                # No features in this page, we're done
                break
        
        # Convert all features to GeoDataFrame
        if len(all_features) > 0:
            gdf = gpd.GeoDataFrame.from_features(all_features, crs='EPSG:4326')
            #print(f"✓ Fetched {len(gdf)} total features for {layer_name}")
            return gdf
        else:
            #print(f"⚠ No features found in bounding box for {layer_name}")
            return gpd.GeoDataFrame(crs='EPSG:4326')
            
    except requests.exceptions.RequestException as e:
        #print(f"✗ Error fetching {layer_name} from ArcGIS: {e}")
        # Return what we have so far rather than nothing
        if len(all_features) > 0:
            #print(f"  Returning {len(all_features)} features fetched before error")
            return gpd.GeoDataFrame.from_features(all_features, crs='EPSG:4326')
        return gpd.GeoDataFrame(crs='EPSG:4326')
    
def load_stedin_grids_from_cache(bbox_coords, cache_path='inputs/stedin_cache'):
    """
    Loads Stedin grid data from cached pickle files and filters to bounding box.
    
    Args:
        bbox_coords (list of tuples): Polygon coordinates [(lon, lat), ...] in WGS84
        cache_path (str): Path to directory containing cached pickle files.
    
    Returns:
        tuple: (stedin_gas_gdf, stedin_elec_gdf, stedin_transformers_gdf) - filtered to bounding box
    """
    
    gas_file = os.path.join(cache_path, 'delft_gas_grid.pkl')
    elec_file = os.path.join(cache_path, 'delft_lv_elec_grid.pkl')
    transformer_file = os.path.join(cache_path, 'delft_transformers.pkl')
    
    # Check if cache files exist
    missing_files = []
    if not os.path.exists(gas_file):
        missing_files.append('delft_gas_grid.pkl')
    if not os.path.exists(elec_file):
        missing_files.append('delft_lv_elec_grid.pkl')
    if not os.path.exists(transformer_file):
        missing_files.append('delft_transformers.pkl')
    
    if missing_files:
        raise FileNotFoundError(
            f"Stedin cache files not found in {cache_path}/\n"
            f"Missing files: {', '.join(missing_files)}\n"
            f"Please run cache_stedin_data.ipynb to create cache files."
        )
    
    # Load full cache
    #print(f"Loading Stedin data from cache: {cache_path}/")
    with open(gas_file, 'rb') as f:
        gas_gdf_full = pickle.load(f)
    
    with open(elec_file, 'rb') as f:
        elec_gdf_full = pickle.load(f)
    
    with open(transformer_file, 'rb') as f:
        transformers_gdf_full = pickle.load(f)
    
    #print(f"Loaded {len(gas_gdf_full):,} gas features, {len(elec_gdf_full):,} elec features, {len(transformers_gdf_full):,} transformers from cache")
    
    # Create polygon for filtering
    polygon = Polygon(bbox_coords)
    
    # Filter gas network to bounding box
    if not gas_gdf_full.empty:
        gas_gdf = gas_gdf_full[gas_gdf_full.geometry.intersects(polygon)].reset_index(drop=True).copy()
    else:
        gas_gdf = gpd.GeoDataFrame(crs='EPSG:4326')
    
    # Filter electricity network to bounding box
    if not elec_gdf_full.empty:
        elec_gdf = elec_gdf_full[elec_gdf_full.geometry.intersects(polygon)].reset_index(drop=True).copy()
    else:
        elec_gdf = gpd.GeoDataFrame(crs='EPSG:4326')
    
    # Filter transformers to bounding box
    if not transformers_gdf_full.empty:
        transformers_gdf = transformers_gdf_full[transformers_gdf_full.geometry.intersects(polygon)].reset_index(drop=True).copy()
    else:
        transformers_gdf = gpd.GeoDataFrame(crs='EPSG:4326')
    
    #print(f"Filtered to {len(gas_gdf):,} gas features, {len(elec_gdf):,} elec features, {len(transformers_gdf):,} transformers in bounding box")
    
    return gas_gdf, elec_gdf, transformers_gdf

def visualize_network_topology(heat_gdf, elec_gdf, transformers_gdf, bbox_coords, 
                               heat_label="Heat Network", elec_label="Electricity Network",
                               output_file="debug/topology_map.html"):
    """
    Creates an interactive Folium map visualization of heat/gas and electricity networks.
    Works for both Stedin and OSM data sources.
    
    Args:
        heat_gdf (GeoDataFrame): Heat/gas network features
        elec_gdf (GeoDataFrame): Electricity network features
        transformers_gdf (GeoDataFrame): Transformer locations
        bbox_coords (list of tuples): Bounding box coordinates for fallback centering
        heat_label (str): Label for heat network layer (default: "Heat Network")
        elec_label (str): Label for electricity network layer (default: "Electricity Network")
        output_file (str): Path to save the HTML map (default: "debug/topology_map.html")
    
    Returns:
        None (saves map to output_file)
    """
    # Determine map center
    center_gdf = heat_gdf if not heat_gdf.empty else elec_gdf
    
    if not center_gdf.empty:
        # Project to local CRS for accurate centroid calculation
        center_gdf_proj = center_gdf.to_crs(epsg=28992)
        centroids_proj = center_gdf_proj.geometry.centroid
        centroids_wgs = centroids_proj.to_crs(epsg=4326)
        center = [centroids_wgs.y.mean(), centroids_wgs.x.mean()]
    else:
        # Fallback to bbox center
        lons = [c[0] for c in bbox_coords]
        lats = [c[1] for c in bbox_coords]
        center = [sum(lats)/len(lats), sum(lons)/len(lons)]
    
    # Create the map
    network_map = folium.Map(location=center, zoom_start=15, tiles="OpenStreetMap")
    
    # Create FeatureGroups for each network
    heat_group = folium.FeatureGroup(name=heat_label, show=True)
    elec_group = folium.FeatureGroup(name=elec_label, show=True)
    transformer_group = folium.FeatureGroup(name="MV-LV Transformers", show=True)
    
    # Add heat features
    if not heat_gdf.empty:
        for _, row in heat_gdf.iterrows():
            # Get feature name if it exists, otherwise use index
            feature_name = row.get('feature_name', f'feature_{row.name}')
            folium.GeoJson(
                row.geometry,
                name=feature_name,
                popup=folium.Popup(feature_name, parse_html=True),
                style_function=lambda x: {'color': '#ff5100', 'weight': 3}
            ).add_to(heat_group)
    
    # Add electricity features
    if not elec_gdf.empty:
        for _, row in elec_gdf.iterrows():
            # Get feature name if it exists, otherwise use index
            feature_name = row.get('feature_name', f'feature_{row.name}')
            folium.GeoJson(
                row.geometry,
                name=feature_name,
                popup=folium.Popup(feature_name, parse_html=True),
                style_function=lambda x: {'color': '#3186cc', 'weight': 3}
            ).add_to(elec_group)
    
    # Add transformer features
    if not transformers_gdf.empty:
        for _, row in transformers_gdf.iterrows():
            # Get centroid if geometry is not a Point
            geom = row.geometry
            if geom.geom_type == 'Point':
                location = [geom.y, geom.x]
            else:
                # For Polygon/MultiPolygon, use centroid
                centroid = geom.centroid
                location = [centroid.y, centroid.x]
            
            feature_name = row.get('feature_name', f'transformer_{row.name}')
            folium.CircleMarker(
                location=location,
                radius=5,
                popup=folium.Popup(feature_name, parse_html=True),
                color='#8B4513',
                fill=True,
                fillColor='#8B4513',
                fillOpacity=0.8
            ).add_to(transformer_group)
    
    # Add groups to map
    heat_group.add_to(network_map)
    elec_group.add_to(network_map)
    transformer_group.add_to(network_map)
    
    # Add layer control for toggling
    folium.LayerControl().add_to(network_map)
    
    # Save map
    network_map.save(output_file)
    #print(f"✓ Saved visualization to {output_file}")

def filter_features_within_buildings(gdf, buildings_gdf, buffer_distance=0.0001):
    """
    Remove grid features that are entirely within building footprints.
    
    Args:
        gdf: GeoDataFrame of grid features (lines) in EPSG:4326
        buildings_gdf: GeoDataFrame of building polygons in EPSG:28992
        buffer_distance: Small buffer in degrees to avoid edge cases (default: ~10m)
    
    Returns:
        GeoDataFrame with features inside buildings removed
    """
    if gdf.empty or buildings_gdf is None or buildings_gdf.empty:
        return gdf
    
    # Convert grid to same CRS as buildings (EPSG:28992)
    gdf_projected = gdf.to_crs(epsg=28992)
    
    # Create union of all building polygons for faster checking
    buildings_union = buildings_gdf.unary_union
    
    # Filter: keep only features NOT entirely within buildings
    mask = ~gdf_projected.geometry.apply(lambda geom: buildings_union.contains(geom))
    
    return gdf[mask].reset_index(drop=True)

def process_stedin_grids(
    bbox_coords,
    buildings_df=None,
    features_to_remove_heat=None,
    features_to_remove_elec=None,
    mode='plot',
    online=True,
    cache_path='inputs/stedin_cache', 
    base_service_url="https://services-eu1.arcgis.com/IQto421Ac9MzEmFT/arcgis/rest/services/KM_Gasvervangingsdata/FeatureServer",
    gas_layer_id=1,
    lv_elec_layer_id=2,
    transformer_layer_id=6,
    simplify_tolerance=0.000001,
    snap_tolerance=0.000001
):
    """
    Fetches and processes Stedin heat and electricity grid data from ArcGIS REST API or cache.
    
    Args:
        bbox_coords (list of tuples): Polygon coordinates defining the area of interest.
        buildings_df (pd.DataFrame, optional): Buildings dataframe to filter features within buildings.
        features_to_remove_heat (list of str): Heat/gas network feature names to exclude.
        features_to_remove_elec (list of str): Electricity network feature names to exclude.
        mode (str): If 'plot', creates interactive map visualizations. Default is 'plot'.
        online (bool): If True, fetch from Stedin API; if False, load from cache. Default is True.
        cache_path (str): Path to cache directory (used when online=False). Default is 'inputs/stedin_cache'.
        base_service_url (str): Base URL for Stedin ArcGIS FeatureServer
        gas_layer_id (int): Layer ID for gas network (default: 1)
        lv_elec_layer_id (int): Layer ID for low voltage electricity grid (default: 2)
        transformer_layer_id (int): Layer ID for MV-LV transformers (default: 6)
        simplify_tolerance (float): Geometry simplification precision (in degrees).
        snap_tolerance (float): Geometry snapping threshold (in degrees).
    
    Returns:
        tuple: (stedin_heat_gdf_delft, stedin_elec_gdf_delft, stedin_transformers_gdf_delft)
            - stedin_heat_gdf_delft: Cleaned heat/gas network GeoDataFrame
            - stedin_elec_gdf_delft: Cleaned electricity network GeoDataFrame
            - stedin_transformers_gdf_delft: MV-LV transformers GeoDataFrame
    """
    
    # --- Fetch grid data from ArcGIS REST API or load from cache ---
    
    #print("\n" + "="*80)
    #print("FETCHING STEDIN DATA")
    #print("="*80)
    
    if online:
        # Online mode: Fetch from ArcGIS REST API
        # Fetch Layer 1: Gas grid
        gas_layer_url = f"{base_service_url}/{gas_layer_id}"
        stedin_heat_gdf = fetch_stedin_layer_from_arcgis(bbox_coords, gas_layer_url, "Gas Grid")
        
        # Fetch Layer 2: Low voltage electricity grid
        lv_elec_layer_url = f"{base_service_url}/{lv_elec_layer_id}"
        stedin_elec_gdf = fetch_stedin_layer_from_arcgis(bbox_coords, lv_elec_layer_url, "LV Electricity Grid")
        
        # Fetch Layer 6: MV-LV transformers
        transformer_layer_url = f"{base_service_url}/{transformer_layer_id}"
        stedin_transformers_gdf = fetch_stedin_layer_from_arcgis(bbox_coords, transformer_layer_url, "MV-LV Transformers")
    else:
        # Offline mode: Load from cache
        stedin_heat_gdf, stedin_elec_gdf, stedin_transformers_gdf = load_stedin_grids_from_cache(
            bbox_coords,
            cache_path=cache_path
        )
    
    #print("="*80 + "\n")
    
    # --- Filter and process data ---
    
    # Create the polygon for area of interest
    polygon = Polygon(bbox_coords)
    
    # Process gas network
    if not stedin_heat_gdf.empty:
        stedin_heat_gdf_delft = stedin_heat_gdf[stedin_heat_gdf.geometry.intersects(polygon)].reset_index(drop=True).copy()
        stedin_heat_gdf_delft['feature_name'] = [f"heat_feature{i}" for i in range(len(stedin_heat_gdf_delft))]
        
        # NEW: Remove features within buildings
        if buildings_df is not None:
            buildings_gdf = gpd.GeoDataFrame(buildings_df, geometry='geometry', crs='EPSG:28992')
            stedin_heat_gdf_delft = filter_features_within_buildings(
                stedin_heat_gdf_delft, 
                buildings_gdf
            )
        
        # OLD manual filtering (now optional fallback)
        if features_to_remove_heat:
            stedin_heat_gdf_delft = stedin_heat_gdf_delft[
                ~stedin_heat_gdf_delft['feature_name'].isin(features_to_remove_heat)
            ].reset_index(drop=True).copy()
    
    # Process electricity network
    if not stedin_elec_gdf.empty:
        # Filter geometries that intersect the polygon
        stedin_elec_gdf_delft = stedin_elec_gdf[stedin_elec_gdf.geometry.intersects(polygon)].reset_index(drop=True).copy()
        stedin_elec_gdf_delft['feature_name'] = [f"elec_feature{i}" for i in range(len(stedin_elec_gdf_delft))]
        
        # NEW: Remove features within buildings
        if buildings_df is not None:
            buildings_gdf = gpd.GeoDataFrame(buildings_df, geometry='geometry', crs='EPSG:28992')
            stedin_elec_gdf_delft = filter_features_within_buildings(
                stedin_elec_gdf_delft, 
                buildings_gdf
            )
        
        # OLD manual filtering (now optional fallback)
        if features_to_remove_elec:
            stedin_elec_gdf_delft = stedin_elec_gdf_delft[
                ~stedin_elec_gdf_delft['feature_name'].isin(features_to_remove_elec)
            ].reset_index(drop=True).copy()
        
        
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
    else:
        stedin_elec_gdf_delft = gpd.GeoDataFrame(crs='EPSG:4326')
    
    # Process transformers
    if not stedin_transformers_gdf.empty:
        stedin_transformers_gdf_delft = stedin_transformers_gdf[
            stedin_transformers_gdf.geometry.intersects(polygon)
        ].reset_index(drop=True).copy()
        stedin_transformers_gdf_delft['feature_name'] = [
            f"transformer{i}" for i in range(len(stedin_transformers_gdf_delft))
        ]
    else:
        stedin_transformers_gdf_delft = gpd.GeoDataFrame(crs='EPSG:4326')
    
    # --- Visualization (optional) ---
    if mode == 'plot':
        visualize_network_topology(
            heat_gdf=stedin_heat_gdf_delft,
            elec_gdf=stedin_elec_gdf_delft,
            transformers_gdf=stedin_transformers_gdf_delft,
            bbox_coords=bbox_coords,
            heat_label="Gas Network",
            elec_label="LV Electricity Network",
            output_file="debug/topology_map.html"
        )
    
    return stedin_heat_gdf_delft, stedin_elec_gdf_delft, stedin_transformers_gdf_delft

def process_network_topology(
    bbox_coords,
    buildings_df=None,
    topology_source='stedin',
    osm_pbf_path='inputs/delft.osm.pbf',
    features_to_remove_heat=None,
    features_to_remove_elec=None,
    mode='plot',
    online=True, 
    cache_path='inputs/stedin_cache',  
    base_service_url="https://services-eu1.arcgis.com/IQto421Ac9MzEmFT/arcgis/rest/services/KM_Gasvervangingsdata/FeatureServer",
    gas_layer_id=1,
    lv_elec_layer_id=2,
    transformer_layer_id=6,
    simplify_tolerance=0.000001,
    snap_tolerance=0.000001
):
    """
    Unified function to process network topology from either Stedin grids or OpenStreetMap.
    Always fetches transformer locations from Stedin regardless of topology source.
    
    Args:
        bbox_coords (list of tuples): Polygon coordinates defining the area of interest
        buildings_df (pd.DataFrame, optional): Buildings dataframe to filter features within buildings
        topology_source (str): 'stedin' or 'osm' - source for network topology
        osm_pbf_path (str): Path to OSM PBF file (used when topology_source='osm')
        features_to_remove_heat (list): Heat/gas network feature names to exclude (Stedin only)
        features_to_remove_elec (list): Electricity network feature names to exclude (Stedin only)
        mode (str): If 'plot', creates interactive map visualizations
        online (bool): If True, fetch from Stedin API; if False, load from cache
        cache_path (str): Path to cache directory (used when online=False)
        base_service_url (str): Base URL for Stedin ArcGIS FeatureServer
        gas_layer_id (int): Layer ID for gas network (default: 1)
        lv_elec_layer_id (int): Layer ID for low voltage electricity grid (default: 2)
        transformer_layer_id (int): Layer ID for MV-LV transformers (default: 6)
        simplify_tolerance (float): Geometry simplification precision (in degrees)
        snap_tolerance (float): Geometry snapping threshold (in degrees)
    
    Returns:
        tuple: (heat_gdf, elec_gdf, transformers_gdf)
            - heat_gdf: Heat/gas network GeoDataFrame
            - elec_gdf: Electricity network GeoDataFrame
            - transformers_gdf: MV-LV transformers GeoDataFrame (from Stedin)
    """
    if topology_source.lower() == 'osm':
        
        # Extract roads from OSM
        heat_gdf, elec_gdf = extract_osm_roads(
            osm_pbf_path=osm_pbf_path,
            bbox_coords=bbox_coords,
            buildings_df=buildings_df
        )
        
        # Apply simplification and snapping to OSM roads
        if not heat_gdf.empty:
            heat_gdf['geometry'] = heat_gdf['geometry'].apply(
                lambda geom: geom.simplify(simplify_tolerance, preserve_topology=True)
            )
            # Snap heat features together
            all_geoms = list(heat_gdf.geometry)
            snapped_geoms = []
            for i, geom in enumerate(all_geoms):
                snapped = geom
                for j, other in enumerate(all_geoms):
                    if i != j:
                        snapped = snap(snapped, other, snap_tolerance)
                snapped_geoms.append(snapped)
            heat_gdf['geometry'] = snapped_geoms
        
        if not elec_gdf.empty:
            elec_gdf['geometry'] = elec_gdf['geometry'].apply(
                lambda geom: geom.simplify(simplify_tolerance, preserve_topology=True)
            )
            # Snap electricity features together
            all_geoms = list(elec_gdf.geometry)
            snapped_geoms = []
            for i, geom in enumerate(all_geoms):
                snapped = geom
                for j, other in enumerate(all_geoms):
                    if i != j:
                        snapped = snap(snapped, other, snap_tolerance)
                snapped_geoms.append(snapped)
            elec_gdf['geometry'] = snapped_geoms
        
        # Fetch transformers from Stedin (regardless of topology source)
        transformer_layer_url = f"{base_service_url}/{transformer_layer_id}"
        stedin_transformers_gdf = fetch_stedin_layer_from_arcgis(
            bbox_coords, 
            transformer_layer_url, 
            "MV-LV Transformers"
        )
        
        # Filter transformers to bounding polygon
        polygon = Polygon(bbox_coords)
        if not stedin_transformers_gdf.empty:
            transformers_gdf = stedin_transformers_gdf[
                stedin_transformers_gdf.geometry.intersects(polygon)
            ].reset_index(drop=True).copy()
            transformers_gdf['feature_name'] = [
                f"transformer{i}" for i in range(len(transformers_gdf))
            ]
        else:
            transformers_gdf = gpd.GeoDataFrame(crs='EPSG:4326')
        
        # --- Visualization for OSM (if mode=='plot') ---
        if mode == 'plot':
            visualize_network_topology(
                heat_gdf=heat_gdf,
                elec_gdf=elec_gdf,
                transformers_gdf=transformers_gdf,
                bbox_coords=bbox_coords,
                heat_label="OSM Heat Network",
                elec_label="OSM Electricity Network",
                output_file="debug/topology_map.html"
            )
        
        return heat_gdf, elec_gdf, transformers_gdf
        
    else:  # stedin
        # Use existing Stedin processing (includes transformers and visualization)
        return process_stedin_grids(
            bbox_coords=bbox_coords,
            buildings_df=buildings_df,
            features_to_remove_heat=features_to_remove_heat,
            features_to_remove_elec=features_to_remove_elec,
            mode=mode,
            online=online,  
            cache_path=cache_path,  
            base_service_url=base_service_url,
            gas_layer_id=gas_layer_id,
            lv_elec_layer_id=lv_elec_layer_id,
            transformer_layer_id=transformer_layer_id,
            simplify_tolerance=simplify_tolerance,
            snap_tolerance=snap_tolerance
        )
    
    