import geopandas as gpd
from shapely.geometry import Polygon, LineString
import pyrosm
import pandas as pd
import warnings

# Suppress pyrosm FutureWarning about pandas 3.0 chained assignment
warnings.filterwarnings("ignore", category=FutureWarning, module="pyrosm")



def extract_osm_roads(osm_pbf_path, bbox_coords, buildings_df=None):
    """
    Extract road networks from OpenStreetMap PBF file within a bounding box.
    Creates two identical GeoDataFrames (for heat and electricity) with the same structure
    as Stedin grids to maintain compatibility with existing network building code.
    
    Uses the intersection-based approach: identifies road intersections and endpoints
    to create a realistic network topology.
    
    Args:
        osm_pbf_path (str): Path to the OSM PBF file
        bbox_coords (list of tuples): Polygon coordinates defining the area of interest [(lon, lat), ...]
        buildings_df (pd.DataFrame, optional): Buildings dataframe to filter out roads within buildings
    
    Returns:
        tuple: (osm_heat_gdf, osm_elec_gdf) - Two identical GeoDataFrames with road networks
               - geometry: LineString objects in EPSG:4326
               - feature_name: Unique identifier for each road segment
    """
    # Create bounding box polygon
    bbox_polygon = Polygon(bbox_coords)
    
    #print(f"Loading OSM road network from {osm_pbf_path}...")
    
    try:
        # Read OSM data with bounding polygon
        osm = pyrosm.OSM(osm_pbf_path, bounding_box=bbox_polygon)
        
        # Get all roads (network_type="all" includes all road types)
        streets = osm.get_network(network_type="cycling")
        
        if streets is None or streets.empty:
            print("No road features found in OSM data")
            empty_gdf = gpd.GeoDataFrame(columns=['geometry', 'feature_name'], crs='EPSG:4326')
            return empty_gdf, empty_gdf.copy()
        
        #print(f"✓ Loaded {len(streets)} road features from OSM")
        
        # Ensure geometries are LineStrings or MultiLineStrings
        streets = streets[streets.geometry.type.isin(["LineString", "MultiLineString"])].copy()
        
        # Explode MultiLineStrings to individual LineStrings
        streets_exploded = streets.explode(index_parts=False).reset_index(drop=True)
        
        #print(f"✓ Exploded to {len(streets_exploded)} LineString segments")
        
        # Ensure geometry is in EPSG:4326
        if streets_exploded.crs != 'EPSG:4326':
            streets_exploded = streets_exploded.to_crs('EPSG:4326')
        
        # Filter out roads within buildings if provided
        if buildings_df is not None:
            #print("Filtering roads within building footprints...")
            buildings_gdf = gpd.GeoDataFrame(buildings_df, geometry='geometry', crs='EPSG:28992')
            roads_projected = streets_exploded.to_crs(epsg=28992)
            buildings_union = buildings_gdf.unary_union
            mask = ~roads_projected.geometry.apply(lambda geom: buildings_union.contains(geom))
            streets_exploded = streets_exploded[mask].reset_index(drop=True)
            #print(f"✓ {len(streets_exploded)} road segments after filtering")
        
        # Add feature names for tracking
        streets_exploded['feature_name'] = [f"osm_road{i}" for i in range(len(streets_exploded))]
        
        # Keep only necessary columns and geometry
        roads_clean = streets_exploded[['geometry', 'feature_name']].copy()
        
        # Return two copies - one for heat, one for electricity
        # This maintains compatibility with existing code structure
        heat_gdf = roads_clean.copy()
        elec_gdf = roads_clean.copy()
        
        #print(f"✓ Created heat and electricity network geodataframes with {len(heat_gdf)} segments each")
        
        return heat_gdf, elec_gdf
        
    except Exception as e:
        print(f"✗ Error extracting OSM roads: {e}")
        import traceback
        traceback.print_exc()
        empty_gdf = gpd.GeoDataFrame(columns=['geometry', 'feature_name'], crs='EPSG:4326')
        return empty_gdf, empty_gdf.copy()