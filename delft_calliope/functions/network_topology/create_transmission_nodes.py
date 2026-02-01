"""
Transmission Nodes Creation Module

This module extracts and interpolates transmission nodes from heat and
electricity network geometries.
"""

import numpy as np
import geopandas as gpd
from shapely.geometry import Point

from functions.network_topology.grid_utils import haversine_distance, interpolate_line


def create_transmission_nodes(stedin_heat_gdf_delft, stedin_elec_gdf_delft, spacing_m=None):
    """
    Extracts transmission nodes from heat and electricity networks, with optional interpolation.
    
    Parameters
    ----------
    stedin_heat_gdf_delft : GeoDataFrame
        Cleaned heat/gas network with LineString geometries.
    stedin_elec_gdf_delft : GeoDataFrame
        Cleaned electricity network with LineString geometries.
    spacing_m : float or None
        Spacing in meters for node interpolation along line segments.
        - If provided (e.g., 3.5): Interpolates nodes at this spacing
        - If None: Returns only corner/endpoint nodes (no interpolation)
    
    Returns
    -------
    tuple
        (heat_interp_gdf, elec_interp_gdf)
        - heat_interp_gdf: GeoDataFrame with heat network nodes (interpolated or corners only)
        - elec_interp_gdf: GeoDataFrame with electricity network nodes (interpolated or corners only)
    """
    
    def extract_and_interpolate_nodes(gdf, spacing_m):
        # Collect all unique corner points from all geometries
        corner_points = set()
        for geom in gdf.geometry:
            if geom.geom_type == "LineString":
                for coord in geom.coords:
                    corner_points.add(coord)
            elif geom.geom_type == "MultiLineString":
                for part in geom.geoms:
                    for coord in part.coords:
                        corner_points.add(coord)

        # If no interpolation requested, return only corner nodes
        if spacing_m is None:
            unique_points = [(lat, lon) for lon, lat in corner_points]
            nodes_gdf = gpd.GeoDataFrame(
                geometry=[Point(lon, lat) for lat, lon in unique_points],
                crs=gdf.crs
            )
            nodes_gdf["lon"] = nodes_gdf.geometry.x
            nodes_gdf["lat"] = nodes_gdf.geometry.y
            return nodes_gdf

        # Interpolate along all segments
        interpolated_points = []
        for geom in gdf.geometry:
            if geom.geom_type == "LineString":
                coords = list(geom.coords)
                for i in range(len(coords) - 1):
                    lat1, lon1 = coords[i][1], coords[i][0]
                    lat2, lon2 = coords[i+1][1], coords[i+1][0]
                    points = interpolate_line(lat1, lon1, lat2, lon2, spacing_m=spacing_m)
                    interpolated_points.extend(points)
            elif geom.geom_type == "MultiLineString":
                for part in geom.geoms:
                    coords = list(part.coords)
                    for i in range(len(coords) - 1):
                        lat1, lon1 = coords[i][1], coords[i][0]
                        lat2, lon2 = coords[i+1][1], coords[i+1][0]
                        points = interpolate_line(lat1, lon1, lat2, lon2, spacing_m=spacing_m)
                        interpolated_points.extend(points)

        # Remove duplicates and create GeoDataFrame
        unique_points = list({(round(lat, 7), round(lon, 7)) for lat, lon in interpolated_points})
        interp_gdf = gpd.GeoDataFrame(
            geometry=[Point(lon, lat) for lat, lon in unique_points],
            crs="EPSG:4326"
        )
        interp_gdf["lat"] = interp_gdf.geometry.y
        interp_gdf["lon"] = interp_gdf.geometry.x

        return interp_gdf

    # Extract and optionally interpolate heat (gas) nodes
    heat_interp_gdf = extract_and_interpolate_nodes(stedin_heat_gdf_delft, spacing_m)

    # Extract and optionally interpolate electricity nodes
    elec_interp_gdf = extract_and_interpolate_nodes(stedin_elec_gdf_delft, spacing_m)

    return heat_interp_gdf, elec_interp_gdf
