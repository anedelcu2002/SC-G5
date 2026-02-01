"""
Node Factory Module

Functions for creating different types of network nodes:
- Demand nodes (buildings with heat demand)
- Heat transmission nodes
- Electricity transmission nodes
- Transformer nodes
- Substation nodes
"""

import pandas as pd
import numpy as np


def create_transformer_nodes(stedin_transformers_gdf, transformer_supply_capacity):
    """
    Generate transformer nodes from GeoDataFrame of transformer locations.
    
    Parameters:
    -----------
    stedin_transformers_gdf : gpd.GeoDataFrame
        MV-LV transformer locations with Polygon geometries in EPSG:4326
    transformer_supply_capacity : int
        Maximum electricity supply capacity per transformer in kW
    
    Returns:
    --------
    tuple
        (transformer_nodes_coordinates, transformer_nodes_techs) DataFrames
    """
    if stedin_transformers_gdf.empty:
        return (
            pd.DataFrame(columns=['nodes', 'latitude', 'longitude', 'comment']),
            pd.DataFrame(columns=['nodes', 'techs', 'parameters', 'timesteps', '2050/01/01 00:00'])
        )
    
    # Convert to projected CRS for accurate centroid calculation
    transformers_projected = stedin_transformers_gdf.to_crs(epsg=28992)
    centroids_projected = transformers_projected.geometry.centroid
    
    # Convert centroids back to WGS84
    centroids_wgs84 = centroids_projected.to_crs(epsg=4326)
    
    # Create transformer node names (1-based indexing for consistency)
    transformer_node_names = [f"MV_LV_transformer{i+1}" for i in range(len(stedin_transformers_gdf))]
    
    # Create transformer nodes coordinates DataFrame
    transformer_nodes_coordinates = pd.DataFrame({
        'nodes': transformer_node_names,
        'latitude': centroids_wgs84.y.values,
        'longitude': centroids_wgs84.x.values,
        'comment': ''
    })
    
    # Create transformer nodes techs DataFrame
    transformer_nodes_techs = pd.DataFrame({
        'nodes': transformer_node_names,
        'techs': 'supply_LV_electricity',
        'parameters': 'source_use_max',
        'timesteps': '',
        '2050/01/01 00:00': transformer_supply_capacity
    })
    
    return transformer_nodes_coordinates, transformer_nodes_techs


def create_demand_nodes(merged_df, debug_single_node=False):
    """
    Create demand nodes from building/heat demand data.
    
    Parameters:
    -----------
    merged_df : pd.DataFrame
        Demand nodes with building data and heat demand 
        (contains 'id', 'lon', 'lat', 'Peak heat demand (kW)')
    debug_single_node : bool
        If True, only keep one demand node for quick debugging
    
    Returns:
    --------
    tuple
        (demand_nodes, demand_techs, demand_coords) DataFrames
    """
    demand_nodes = merged_df.copy()
    # Remove any non-numeric prefix, keep only numbers, then add 'D' prefix
    demand_nodes['id'] = 'D' + demand_nodes['id'].astype(str).str.extract(r'(\d+)', expand=False)
    
    # Debug mode: keep only one demand node
    if debug_single_node:
        print(" DEBUG MODE: Keeping only 1 demand node for testing")
        demand_nodes = demand_nodes.iloc[[0]].copy()
    
    # Create demand node techs
    demand_techs = pd.DataFrame({
        "nodes": demand_nodes["id"],
        "techs": "demand_LQ_heat",
        "parameters": "sink_use_equals",
        "timesteps": "",
        "2050/01/01 00:00": demand_nodes["Peak heat demand (kW)"]
    })
    
    # Create demand node coordinates
    demand_coords = demand_nodes[["id", "lon", "lat"]].copy().rename(
        columns={"id": "nodes", "lon": "longitude", "lat": "latitude"}
    )
    
    return demand_nodes, demand_techs, demand_coords


def create_transmission_nodes_df(heat_interp_gdf, elec_interp_gdf):
    """
    Create heat and electricity transmission node DataFrames.
    
    Parameters:
    -----------
    heat_interp_gdf : gpd.GeoDataFrame
        Heat transmission nodes with geometry (contains 'lon', 'lat')
    elec_interp_gdf : gpd.GeoDataFrame
        Electricity transmission nodes with geometry (contains 'lon', 'lat')
    
    Returns:
    --------
    tuple
        (heat_trans_nodes, elec_trans_nodes, heat_trans_techs, elec_trans_techs, 
         heat_trans_coords, elec_trans_coords)
    """
    # Create heat transmission nodes
    heat_trans_nodes = heat_interp_gdf.copy()
    heat_trans_nodes["id"] = [f"LQHtransmission{i+1}" for i in range(len(heat_trans_nodes))]
    
    # Create electricity transmission nodes
    elec_trans_nodes = elec_interp_gdf.copy()
    elec_trans_nodes["id"] = [f"LVEtransmission{i+1}" for i in range(len(elec_trans_nodes))]
    
    # Create heat transmission node techs
    heat_trans_techs = pd.DataFrame({
        "nodes": heat_trans_nodes["id"],
        "techs": "demand_LQ_heat",
        "parameters": "sink_use_equals",
        "timesteps": "",
        "2050/01/01 00:00": 0
    })
    
    # Create electricity transmission node techs
    elec_trans_techs = pd.DataFrame({
        "nodes": elec_trans_nodes["id"],
        "techs": "demand_electricity",
        "parameters": "sink_use_equals",
        "timesteps": "",
        "2050/01/01 00:00": 0
    })
    
    # Create coordinates DataFrames
    heat_trans_coords = heat_trans_nodes[["id", "lon", "lat"]].copy().rename(
        columns={"id": "nodes", "lon": "longitude", "lat": "latitude"}
    )
    elec_trans_coords = elec_trans_nodes[["id", "lon", "lat"]].copy().rename(
        columns={"id": "nodes", "lon": "longitude", "lat": "latitude"}
    )
    
    return (heat_trans_nodes, elec_trans_nodes, 
            heat_trans_techs, elec_trans_techs,
            heat_trans_coords, elec_trans_coords)


def combine_all_nodes(warmtenet_nodes_techs, warmtenet_nodes_coordinates,
                      transformer_nodes_techs, transformer_nodes_coordinates,
                      demand_techs, demand_coords,
                      heat_trans_techs, elec_trans_techs,
                      heat_trans_coords, elec_trans_coords):
    """
    Combine all node types into unified DataFrames.
    
    Returns:
    --------
    tuple
        (nodes_techs, nodes_coordinates) combined DataFrames
    """
    # Combine transmission node techs
    transmission_techs = pd.concat([heat_trans_techs, elec_trans_techs], ignore_index=True)
    new_techs = pd.concat([demand_techs, transmission_techs], ignore_index=True)
    old_techs = pd.concat([warmtenet_nodes_techs, transformer_nodes_techs], ignore_index=True)
    nodes_techs = pd.concat([old_techs, new_techs], ignore_index=True)
    
    # Combine transmission node coordinates
    trans_coords = pd.concat([heat_trans_coords, elec_trans_coords], ignore_index=True)
    new_coords = pd.concat([demand_coords, trans_coords], ignore_index=True)
    old_coords = pd.concat([warmtenet_nodes_coordinates, transformer_nodes_coordinates], ignore_index=True)
    nodes_coordinates = pd.concat([old_coords, new_coords], ignore_index=True)
    
    return nodes_techs, nodes_coordinates


def add_substation_node(nodes_coordinates, nodes_techs, substation_name, sub_lat, sub_lon):
    """
    Add a substation node to the network.
    
    Parameters:
    -----------
    nodes_coordinates : pd.DataFrame
        Existing node coordinates
    nodes_techs : pd.DataFrame
        Existing node techs
    substation_name : str
        Name for the substation node
    sub_lat : float
        Latitude of substation
    sub_lon : float
        Longitude of substation
    
    Returns:
    --------
    tuple
        (updated_nodes_coordinates, updated_nodes_techs)
    """
    # Add substation to nodes_coordinates
    substation_coord_row = pd.DataFrame({
        'nodes': [substation_name],
        'latitude': [sub_lat],
        'longitude': [sub_lon],
        'comment': ['']
    })
    nodes_coordinates = pd.concat([nodes_coordinates, substation_coord_row], ignore_index=True)
    
    # Add substation to nodes_techs (placeholder, actual tech defined in YAML)
    substation_tech_row = pd.DataFrame({
        'nodes': [substation_name],
        'techs': ['heat_main'],
        'parameters': ['sink_use_equals'],
        'timesteps': [''],
        '2050/01/01 00:00': [0]
    })
    nodes_techs = pd.concat([nodes_techs, substation_tech_row], ignore_index=True)
    
    return nodes_coordinates, nodes_techs
