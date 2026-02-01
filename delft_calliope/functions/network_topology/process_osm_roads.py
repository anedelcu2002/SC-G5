"""
OSM Road Extraction Module

This module extracts road networks from OpenStreetMap PBF files for use
as alternative network topology to Stedin grids.
"""

import geopandas as gpd
from shapely.geometry import Polygon, LineString
import pyrosm
import pandas as pd
import warnings
import logging

# Suppress pyrosm FutureWarning about pandas 3.0 chained assignment
warnings.filterwarnings("ignore", category=FutureWarning, module="pyrosm")

logger = logging.getLogger(__name__)


class OSMExtractionError(Exception):
    """Raised when OSM road extraction fails."""
    pass


def extract_osm_roads(osm_pbf_path, bbox_coords, buildings_df=None):
    """
    Extract road networks from OpenStreetMap PBF file within a bounding box.
    
    Creates two identical GeoDataFrames (for heat and electricity) with the same structure
    as Stedin grids to maintain compatibility with existing network building code.
    Uses the intersection-based approach: identifies road intersections and endpoints
    to create a realistic network topology.
    
    Parameters
    ----------
    osm_pbf_path : str
        Path to the OSM PBF file
    bbox_coords : list of tuples
        Polygon coordinates defining the area of interest [(lon, lat), ...]
    buildings_df : pd.DataFrame, optional
        Buildings dataframe to filter out roads within buildings
    
    Returns
    -------
    tuple
        (osm_heat_gdf, osm_elec_gdf) - Two identical GeoDataFrames with road networks
        - geometry: LineString objects in EPSG:4326
        - feature_name: Unique identifier for each road segment
    
    Raises
    ------
    OSMExtractionError
        If road extraction from the PBF file fails
    """
    # Create bounding box polygon
    bbox_polygon = Polygon(bbox_coords)
    
    try:
        # Read OSM data with bounding polygon
        osm = pyrosm.OSM(osm_pbf_path, bounding_box=bbox_polygon)
        
        # Get all roads (network_type="all" includes all road types)
        streets = osm.get_network(network_type="cycling")
        
        if streets is None or streets.empty:
            logger.warning("No road features found in OSM data")
            empty_gdf = gpd.GeoDataFrame(columns=['geometry', 'feature_name'], crs='EPSG:4326')
            return empty_gdf, empty_gdf.copy()
        
        # Ensure geometries are LineStrings or MultiLineStrings
        streets = streets[streets.geometry.type.isin(["LineString", "MultiLineString"])].copy()
        
        # Explode MultiLineStrings to individual LineStrings
        streets_exploded = streets.explode(index_parts=False).reset_index(drop=True)
        
        # Ensure geometry is in EPSG:4326
        if streets_exploded.crs != 'EPSG:4326':
            streets_exploded = streets_exploded.to_crs('EPSG:4326')
        
        # Filter out roads within buildings if provided
        if buildings_df is not None:
            buildings_gdf = gpd.GeoDataFrame(buildings_df, geometry='geometry', crs='EPSG:28992')
            roads_projected = streets_exploded.to_crs(epsg=28992)
            buildings_union = buildings_gdf.unary_union
            mask = ~roads_projected.geometry.apply(lambda geom: buildings_union.contains(geom))
            streets_exploded = streets_exploded[mask].reset_index(drop=True)
        
        # Add feature names for tracking
        streets_exploded['feature_name'] = [f"osm_road{i}" for i in range(len(streets_exploded))]
        
        # Keep only necessary columns and geometry
        roads_clean = streets_exploded[['geometry', 'feature_name']].copy()
        
        # Return two copies - one for heat, one for electricity
        # This maintains compatibility with existing code structure
        heat_gdf = roads_clean.copy()
        elec_gdf = roads_clean.copy()
        
        return heat_gdf, elec_gdf
        
    except Exception as e:
        logger.error("Failed to extract OSM roads from %s: %s", osm_pbf_path, e, exc_info=True)
        raise OSMExtractionError(f"Failed to extract roads from {osm_pbf_path}") from e
