"""
Model Data Extraction

Functions for extracting coordinates, capacities, and demand data
from Calliope model objects and GeoDataFrames.
"""

import pandas as pd


def extract_coordinates_and_capacities(model):
    """
    Extract node coordinates and flow capacities from a solved Calliope model.
    
    Parameters
    ----------
    model : calliope.Model
        Solved Calliope model with results.
    
    Returns
    -------
    tuple
        (df_coords, df_capacity_coords) where:
        - df_coords: DataFrame with columns ['nodes', 'latitude', 'longitude']
        - df_capacity_coords: DataFrame with coordinates merged with capacity data,
          sorted by 'techs'
    """
    # Extract coordinates
    df_coords = model.inputs[["latitude", "longitude"]].to_dataframe().reset_index()
    
    # Extract flow capacities for transmission technologies
    df_capacity = (
        model.results.flow_cap.where(model.inputs.base_tech == "transmission")
        .to_series()
        .where(lambda x: x != 0)
        .dropna()
        .to_frame("Flow capacity (kW)")
        .reset_index()
    )
    
    # Merge coordinates with capacity data
    df_capacity_coords = pd.merge(
        df_coords, 
        df_capacity, 
        left_on="nodes", 
        right_on="nodes"
    ).sort_values(by=['techs'])
    
    return df_coords, df_capacity_coords


def build_demand_lookup(buildings_gdf):
    """
    Build a lookup dictionary mapping demand node IDs to peak heat demand.
    
    Parameters
    ----------
    buildings_gdf : geopandas.GeoDataFrame
        GeoDataFrame with building data, must contain 'id' and 
        'Peak heat demand (kW)' columns.
    
    Returns
    -------
    dict
        Dictionary mapping demand node IDs (e.g., 'D12345') to demand in kW.
    """
    demand_lookup = {}
    
    for idx, row in buildings_gdf.iterrows():
        building_id = str(row['id'])
        numeric_part = ''.join(filter(str.isdigit, building_id))
        if numeric_part:
            demand_node_id = f"D{numeric_part}"
            demand_lookup[demand_node_id] = row['Peak heat demand (kW)']
    
    return demand_lookup


def extract_unmet_demand(model):
    """
    Extract unmet demand statistics from model results.
    
    Parameters
    ----------
    model : calliope.Model
        Solved Calliope model with results.
    
    Returns
    -------
    tuple
        (unmet_demand_by_node, total_unmet_demand_kw, num_unmet_nodes, total_demand_nodes)
        where:
        - unmet_demand_by_node: dict mapping node names to unmet demand in kW
        - total_unmet_demand_kw: total unmet demand across all nodes
        - num_unmet_nodes: count of demand nodes (starting with 'D') with unmet demand
        - total_demand_nodes: total count of demand nodes
    """
    unmet_demand_by_node = {}
    total_unmet_demand_kw = 0.0
    num_unmet_nodes = 0
    
    if 'unmet_demand' in model.results:
        unmet_series = model.results['unmet_demand'].sum(
            dim=['carriers', 'timesteps'], 
            skipna=True
        )
        for node in unmet_series.nodes.values:
            unmet_value = float(unmet_series.sel(nodes=node).values)
            if unmet_value > 0:
                unmet_demand_by_node[str(node)] = unmet_value
                total_unmet_demand_kw += unmet_value
                if str(node).startswith('D'):
                    num_unmet_nodes += 1
    
    # Count total demand nodes
    all_nodes = model.inputs.coords['nodes'].values
    total_demand_nodes = sum(1 for node in all_nodes if str(node).startswith('D'))
    
    return unmet_demand_by_node, total_unmet_demand_kw, num_unmet_nodes, total_demand_nodes


def get_tech_metadata(model):
    """
    Extract technology names and distances from model inputs.
    
    Parameters
    ----------
    model : calliope.Model
        Calliope model object.
    
    Returns
    -------
    tuple
        (tech_names, tech_distances) where both are pandas Series
        indexed by technology identifier.
    """
    tech_names = model.inputs.name.to_series().dropna()
    tech_distances = model.inputs.distance.to_series().dropna()
    return tech_names, tech_distances


def get_all_nodes(model):
    """
    Get list of all node names from model.
    
    Parameters
    ----------
    model : calliope.Model
        Calliope model object.
    
    Returns
    -------
    list
        List of node name strings.
    """
    if 'nodes' in model.inputs.coords:
        return [str(n) for n in model.inputs.coords['nodes'].values]
    return []
