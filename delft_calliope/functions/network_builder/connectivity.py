"""
Connectivity Module

Functions for checking and repairing network connectivity.
Ensures all demand nodes are connected to both heat and electricity sources.
"""

import pandas as pd
import numpy as np
import networkx as nx


def ensure_demand_connectivity(nodes_coordinates, links_techs, link_parameters, demand_nodes, 
                               heat_trans_nodes, haversine_distance_func):
    """
    Ensure all demand nodes are connected to both heat and electricity network sources.
    
    Checks connectivity separately for heat network (to geothermie/warmtenet/substation nodes)
    and electricity network (to MV_LV_transformer nodes). Creates emergency links for isolated nodes.
    
    Parameters:
    -----------
    nodes_coordinates : pd.DataFrame
        DataFrame with columns ['nodes', 'latitude', 'longitude']
    links_techs : pd.DataFrame
        DataFrame with columns ['techs', 'link_from', 'link_to', ...]
    link_parameters : dict
        Link parameters including 'LQ heat distribution secondary' and 'LV electricity distribution'
    demand_nodes : pd.DataFrame
        Demand nodes DataFrame
    heat_trans_nodes : pd.DataFrame
        Heat transmission nodes DataFrame
    haversine_distance_func : function
        Function to calculate haversine distance
    
    Returns:
    --------
    tuple
        (updated_links_techs, isolated_demand_nodes_set, emergency_links_list)
        - updated_links_techs: DataFrame with emergency links added
        - isolated_demand_nodes_set: Set of all isolated node IDs (heat or electricity)
        - emergency_links_list: List of emergency link dicts that were created
    """
    
    all_node_names = set(nodes_coordinates['nodes'])
    demand_node_ids = set(nodes_coordinates[nodes_coordinates['nodes'].str.startswith('D')]['nodes'])
    
    # Build separate graphs for heat and electricity networks
    G_heat = _build_heat_graph(nodes_coordinates, links_techs)
    G_elec = _build_electricity_graph(nodes_coordinates, links_techs)
    
    # Check heat network connectivity
    heat_isolated_nodes = _find_isolated_heat_nodes(G_heat, all_node_names, demand_node_ids)
    
    # Check electricity network connectivity
    elec_isolated_nodes, elec_connected_nodes = _find_isolated_elec_nodes(
        G_elec, all_node_names, demand_node_ids
    )
    
    # Combine all isolated nodes
    all_isolated_nodes = heat_isolated_nodes | elec_isolated_nodes
    
    if not all_isolated_nodes:
        return links_techs, set(), []
    
    new_links = []
    
    # Create heat emergency links
    heat_component = _get_heat_component(G_heat, all_node_names)
    if heat_isolated_nodes and heat_component:
        heat_emergency = _create_heat_emergency_links(
            nodes_coordinates, heat_isolated_nodes, heat_component,
            link_parameters, haversine_distance_func
        )
        new_links.extend(heat_emergency)
    
    # Create electricity emergency links
    if elec_isolated_nodes and elec_connected_nodes:
        elec_emergency = _create_elec_emergency_links(
            nodes_coordinates, elec_isolated_nodes, elec_connected_nodes,
            link_parameters, haversine_distance_func
        )
        new_links.extend(elec_emergency)
    
    # Append new links to links_techs
    if new_links:
        new_links_df = pd.DataFrame(new_links)
        links_techs = pd.concat([links_techs, new_links_df], ignore_index=True)
    
    return links_techs, all_isolated_nodes, new_links


def _build_heat_graph(nodes_coordinates, links_techs):
    """Build NetworkX graph for heat network only."""
    G_heat = nx.Graph()
    for node in nodes_coordinates['nodes']:
        G_heat.add_node(node)
    
    # Add edges from heat links
    for _, link in links_techs.iterrows():
        tech_name = link.get('techs', '')
        if pd.notna(tech_name):
            is_heat_link = (tech_name.endswith('_heat') or 
                           tech_name.startswith('geothermie_') or 
                           tech_name.startswith('warmtenet') or
                           tech_name.startswith('substation_'))
            if is_heat_link:
                link_from = link.get('link_from')
                link_to = link.get('link_to')
                if pd.notna(link_from) and pd.notna(link_to):
                    G_heat.add_edge(link_from, link_to)
    
    return G_heat


def _build_electricity_graph(nodes_coordinates, links_techs):
    """Build NetworkX graph for electricity network only."""
    G_elec = nx.Graph()
    for node in nodes_coordinates['nodes']:
        G_elec.add_node(node)
    
    # Add edges from electricity links only
    for _, link in links_techs.iterrows():
        tech_name = link.get('techs', '')
        if pd.notna(tech_name) and tech_name.endswith('_electricity'):
            link_from = link.get('link_from')
            link_to = link.get('link_to')
            if pd.notna(link_from) and pd.notna(link_to):
                G_elec.add_edge(link_from, link_to)
    
    return G_elec


def _get_heat_component(G_heat, all_node_names):
    """Find the connected component containing heat sources."""
    heat_source_nodes = {node for node in all_node_names 
                        if node.startswith('geothermie_') or 
                           node.startswith('warmtenet') or 
                           node.startswith('substation_')}
    
    heat_components = list(nx.connected_components(G_heat))
    
    for component in heat_components:
        if heat_source_nodes & component:
            return component
    
    return None


def _find_isolated_heat_nodes(G_heat, all_node_names, demand_node_ids):
    """Find demand nodes isolated from heat sources."""
    heat_component = _get_heat_component(G_heat, all_node_names)
    
    if heat_component is None:
        return set()
    
    return demand_node_ids - heat_component


def _find_isolated_elec_nodes(G_elec, all_node_names, demand_node_ids):
    """
    Find demand nodes isolated from electricity sources.
    
    Returns:
    --------
    tuple
        (isolated_nodes, connected_nodes)
    """
    elec_source_nodes = {node for node in all_node_names 
                        if node.startswith('MV_LV_transformer')}
    
    elec_components = list(nx.connected_components(G_elec))
    
    # Find ALL components containing electricity sources
    elec_components_with_source = []
    for component in elec_components:
        if elec_source_nodes & component:
            elec_components_with_source.append(component)
    
    if not elec_components_with_source:
        return set(), set()
    
    # Union of all components with transformers
    elec_connected_nodes = set().union(*elec_components_with_source)
    elec_isolated_nodes = demand_node_ids - elec_connected_nodes
    
    return elec_isolated_nodes, elec_connected_nodes


def _create_heat_emergency_links(nodes_coordinates, heat_isolated_nodes, heat_component,
                                  link_parameters, haversine_distance_func):
    """Create emergency heat links for isolated demand nodes."""
    new_links = []
    
    # Get heat transmission nodes in heat component
    heat_trans_in_component = nodes_coordinates[
        (nodes_coordinates['nodes'].isin(heat_component)) & 
        ((nodes_coordinates['nodes'].str.startswith('LQHtransmission')) |
         (nodes_coordinates['nodes'].str.startswith('warmtenet')) |
         (nodes_coordinates['nodes'].str.startswith('substation_')))
    ]
    
    if heat_trans_in_component.empty:
        return new_links
    
    isolated_heat_coords = nodes_coordinates[nodes_coordinates['nodes'].isin(heat_isolated_nodes)]
    
    demand_lats = isolated_heat_coords['latitude'].values
    demand_lons = isolated_heat_coords['longitude'].values
    trans_lats = heat_trans_in_component['latitude'].values
    trans_lons = heat_trans_in_component['longitude'].values
    
    # Vectorized distance calculation
    dists = haversine_distance_func(
        demand_lats[:, None], demand_lons[:, None],
        trans_lats[None, :], trans_lons[None, :]
    )
    
    # For each isolated demand node, create heat link to nearest transmission node
    for i, (demand_idx, demand_row) in enumerate(isolated_heat_coords.iterrows()):
        demand_id = demand_row['nodes']
        nearest_idx = np.argmin(dists[i, :])
        nearest_trans_id = heat_trans_in_component.iloc[nearest_idx]['nodes']
        distance_km = dists[i, nearest_idx] / 1000.0
        
        link_name = f"{demand_id}_to_{nearest_trans_id}_heat"
        link_params = link_parameters['LQ heat distribution secondary']
        
        new_links.append({
            'techs': link_name,
            'color': '#823740',
            'name': 'LQ heat distribution secondary',
            'base_tech': 'transmission',
            'flow_cap_max': link_params['flow_cap_max'],
            'flow_out_eff_per_distance': link_params['flow_out_eff_per_distance'],
            'lifetime': 20,
            'link_from': demand_id,
            'link_to': nearest_trans_id,
            'distance': distance_km
        })
    
    return new_links


def _create_elec_emergency_links(nodes_coordinates, elec_isolated_nodes, elec_connected_nodes,
                                  link_parameters, haversine_distance_func):
    """Create emergency electricity links for isolated demand nodes."""
    new_links = []
    
    # Get electricity transmission nodes from all components with transformers
    elec_trans_in_component = nodes_coordinates[
        (nodes_coordinates['nodes'].isin(elec_connected_nodes)) & 
        ((nodes_coordinates['nodes'].str.startswith('LVEtransmission')) |
         (nodes_coordinates['nodes'].str.startswith('MV_LV_transformer')))
    ]
    
    if elec_trans_in_component.empty:
        return new_links
    
    isolated_elec_coords = nodes_coordinates[nodes_coordinates['nodes'].isin(elec_isolated_nodes)]
    
    demand_lats = isolated_elec_coords['latitude'].values
    demand_lons = isolated_elec_coords['longitude'].values
    trans_lats = elec_trans_in_component['latitude'].values
    trans_lons = elec_trans_in_component['longitude'].values
    
    # Vectorized distance calculation
    dists = haversine_distance_func(
        demand_lats[:, None], demand_lons[:, None],
        trans_lats[None, :], trans_lons[None, :]
    )
    
    # For each isolated demand node, create electricity link to nearest transmission node
    for i, (demand_idx, demand_row) in enumerate(isolated_elec_coords.iterrows()):
        demand_id = demand_row['nodes']
        nearest_idx = np.argmin(dists[i, :])
        nearest_trans_id = elec_trans_in_component.iloc[nearest_idx]['nodes']
        distance_km = dists[i, nearest_idx] / 1000.0
        
        link_name = f"{demand_id}_to_{nearest_trans_id}_electricity"
        link_params = link_parameters['LV electricity distribution secondary']
        
        new_links.append({
            'techs': link_name,
            'color': '#505596',
            'name': 'LV electricity distribution secondary',
            'base_tech': 'transmission',
            'flow_cap_max': link_params['flow_cap_max'],
            'flow_out_eff_per_distance': link_params['flow_out_eff_per_distance'],
            'lifetime': 20,
            'link_from': demand_id,
            'link_to': nearest_trans_id,
            'distance': distance_km
        })
    
    return new_links
