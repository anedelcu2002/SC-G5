"""
Electricity Network Loss Calculator

Functions for calculating I²R losses in low-voltage electricity distribution
networks across multiple transformer clusters.
"""

import networkx as nx

from functions.results_processing.extract_model_data import (
    get_tech_metadata,
    get_all_nodes
)


# Default line voltage for LV network
LV_VOLTAGE = 400  # Volts


def calculate_electricity_network_losses(
    df_capacity_coords,
    model,
    distance_factors,
    electricity_resistance_rates,
    voltage=LV_VOLTAGE
):
    """
    Calculate I²R losses in LV electricity networks across all transformer clusters.
    
    This function identifies all transformer nodes, builds a network graph for each
    cluster, and calculates power losses using P_loss = I² × R × distance.
    
    Parameters
    ----------
    df_capacity_coords : pandas.DataFrame
        DataFrame with flow capacities and coordinates from model.
    model : calliope.Model
        Solved Calliope model.
    distance_factors : dict
        Multiplication factors for distances by segment type.
    electricity_resistance_rates : dict
        Resistance values in Ω/km for each cable type.
        Keys: 'LV electricity distribution main', 'LV electricity distribution secondary'
    voltage : float, optional
        Line voltage in Volts (default: 400V).
    
    Returns
    -------
    dict
        Dictionary containing:
        - 'adjusted_capacities': dict of tech -> adjusted capacity in kW
        - 'total_LV_losses_kw': total electricity losses across all clusters
        - 'supply_losses': dict of transformer_node -> cluster losses in kW
        - 'transformer_nodes': list of transformer node names processed
    """
    tech_names, tech_distances = get_tech_metadata(model)
    all_nodes = get_all_nodes(model)
    
    # Build electricity network graph
    G_LV = _build_electricity_network_graph(
        df_capacity_coords, tech_names, tech_distances,
        distance_factors, electricity_resistance_rates
    )
    
    # Build undirected edge mapping
    edges_undirected = {}
    for u, v, data in G_LV.edges(data=True):
        key = tuple(sorted([u, v]))
        if key not in edges_undirected:
            edges_undirected[key] = {
                'tech': data['tech'],
                'distance_km': data['distance_km'],
                'resistance_per_km': data['resistance_per_km']
            }
    
    # Build adjacency list
    neighbors = {}
    for (a, b), data in edges_undirected.items():
        if a not in neighbors:
            neighbors[a] = []
        if b not in neighbors:
            neighbors[b] = []
        neighbors[a].append((b, data))
        neighbors[b].append((a, data))
    
    # Find all transformer nodes
    transformer_nodes = _find_transformer_nodes(all_nodes, neighbors)
    
    # Build electricity demand lookup from heat pump capacities
    elec_demand_lookup = _build_electricity_demand_lookup(model)
    
    # Process each transformer cluster
    all_adjusted_capacities = {}
    all_supply_losses = {}
    total_LV_losses_kw = 0.0
    
    for transformer_name in transformer_nodes:
        cluster_result = _process_transformer_cluster(
            transformer_name, neighbors, elec_demand_lookup, voltage
        )
        
        # Accumulate results
        all_adjusted_capacities.update(cluster_result['edge_capacities'])
        all_supply_losses[transformer_name] = cluster_result['total_losses_kw']
        total_LV_losses_kw += cluster_result['total_losses_kw']
    
    return {
        'adjusted_capacities': all_adjusted_capacities,
        'total_LV_losses_kw': total_LV_losses_kw,
        'supply_losses': all_supply_losses,
        'transformer_nodes': transformer_nodes
    }


def _build_electricity_network_graph(df_capacity_coords, tech_names, tech_distances,
                                      distance_factors, electricity_resistance_rates):
    """
    Build a directed graph representing the electricity network.
    
    Parameters
    ----------
    df_capacity_coords : pandas.DataFrame
        DataFrame with capacity and coordinate data.
    tech_names : pandas.Series
        Technology names indexed by tech identifier.
    tech_distances : pandas.Series
        Technology distances indexed by tech identifier.
    distance_factors : dict
        Distance multiplication factors by segment type.
    electricity_resistance_rates : dict
        Resistance in Ω/km by cable type.
    
    Returns
    -------
    networkx.DiGraph
        Directed graph with edge attributes for loss calculations.
    """
    G = nx.DiGraph()
    
    # Filter to electricity links
    df_links_elec = df_capacity_coords[
        df_capacity_coords['carriers'].str.contains('electricity', case=False, na=False)
    ].copy()
    
    for idx, row in df_links_elec.iterrows():
        parts = row['techs'].rsplit('_to_', 1)
        if len(parts) != 2:
            continue
            
        link_from_carrier, link_to_carrier = parts
        link_from = link_from_carrier.replace('_electricity', '')
        link_to = link_to_carrier.replace('_electricity', '')
        
        tech_name = tech_names.get(row['techs'], 'Unknown')
        distance_km = tech_distances.get(row['techs'], 0)
        distance_km_adjusted = distance_km * distance_factors.get(tech_name, 1.0)
        resistance_per_km = electricity_resistance_rates.get(tech_name, 0.0)
        
        G.add_edge(
            link_to,
            link_from,
            tech=row['techs'],
            tech_name=tech_name,
            capacity_kw=row['Flow capacity (kW)'],
            distance_km=distance_km_adjusted,
            resistance_per_km=resistance_per_km
        )
    
    return G


def _find_transformer_nodes(all_nodes, neighbors):
    """
    Find all transformer nodes that are connected to the network.
    
    Parameters
    ----------
    all_nodes : list
        List of all node names in the model.
    neighbors : dict
        Adjacency list for the electricity network.
    
    Returns
    -------
    list
        List of transformer node names.
    """
    transformer_nodes = []
    for node in all_nodes:
        node_str = str(node)
        node_lower = node_str.lower()
        if ('transformer' in node_lower or 'trafo' in node_lower) and node_str in neighbors:
            transformer_nodes.append(node_str)
    return transformer_nodes


def _build_electricity_demand_lookup(model):
    """
    Build electricity demand lookup from heat pump flow capacities.
    
    Parameters
    ----------
    model : calliope.Model
        Solved Calliope model.
    
    Returns
    -------
    dict
        Dictionary mapping node names to electricity demand in kW.
    """
    elec_demand_lookup = {}
    
    # Check if heat_pump tech exists
    if 'heat_pump' not in model.inputs.coords.get('techs', []):
        return elec_demand_lookup
    
    # Try flow_cap first
    try:
        heat_pump_flow = (
            model.results.flow_cap
            .sel(techs='heat_pump', carriers='electricity')
            .to_series()
            .dropna()
        )
        
        for node, capacity in heat_pump_flow.items():
            if capacity > 0:
                elec_demand_lookup[str(node)] = abs(float(capacity))
        
        return elec_demand_lookup
        
    except (KeyError, ValueError):
        pass
    
    # Fallback to flow_in
    try:
        heat_pump_flow = (
            model.results.flow_in
            .sel(techs='heat_pump', carriers='electricity')
            .max(dim='timesteps')
            .to_series()
            .dropna()
        )
        
        for node, demand in heat_pump_flow.items():
            if demand > 0:
                elec_demand_lookup[str(node)] = abs(float(demand))
                
    except (KeyError, ValueError):
        pass
    
    return elec_demand_lookup


def _process_transformer_cluster(transformer_name, neighbors, elec_demand_lookup, voltage):
    """
    Process a single transformer cluster with I²R loss calculation.
    
    Parameters
    ----------
    transformer_name : str
        Name of the transformer (root) node.
    neighbors : dict
        Adjacency list for the electricity network.
    elec_demand_lookup : dict
        Mapping of node names to electricity demand in kW.
    voltage : float
        Line voltage in Volts.
    
    Returns
    -------
    dict
        Dictionary containing:
        - 'edge_capacities': dict of tech -> required capacity
        - 'segment_losses': dict of tech -> loss in kW
        - 'total_losses_kw': sum of all segment losses
        - 'transformer_requirement': total kW required at transformer
    """
    # BFS from transformer to build tree relationships
    parent_of = {}
    children_of = {}
    edge_to_parent = {}
    
    visited = set()
    queue = [transformer_name]
    visited.add(transformer_name)
    children_of[transformer_name] = []
    
    while queue:
        current = queue.pop(0)
        
        for neighbor, edge_data in neighbors.get(current, []):
            if neighbor not in visited:
                visited.add(neighbor)
                parent_of[neighbor] = current
                edge_to_parent[neighbor] = edge_data
                
                if current not in children_of:
                    children_of[current] = []
                children_of[current].append(neighbor)
                
                if neighbor not in children_of:
                    children_of[neighbor] = []
                
                queue.append(neighbor)
    
    # Initialize required power at each node
    required = {}
    for node in visited:
        required[node] = elec_demand_lookup.get(node, 0.0)
    
    # Find initial leaves
    leaves = set()
    for node in visited:
        if len(children_of[node]) == 0:
            leaves.add(node)
    
    # Collapse branches with I²R loss calculation
    edge_capacity = {}
    segment_losses = {}
    
    while leaves:
        next_leaves = set()
        
        for leaf in leaves:
            if leaf in parent_of:
                parent = parent_of[leaf]
                edge = edge_to_parent[leaf]
                tech = edge['tech']
                distance_km = edge['distance_km']
                resistance_per_km = edge['resistance_per_km']
                
                # Power flowing through this edge
                power_kw = required[leaf]
                
                # I²R loss calculation
                power_w = power_kw * 1000
                current_a = power_w / voltage
                resistance_ohms = resistance_per_km * distance_km
                loss_w = (current_a ** 2) * resistance_ohms
                edge_loss_kw = loss_w / 1000
                
                # Edge capacity = demand + loss
                edge_capacity[tech] = power_kw + edge_loss_kw
                segment_losses[tech] = edge_loss_kw
                
                # Propagate to parent
                required[parent] = required.get(parent, 0.0) + edge_capacity[tech]
                
                children_of[parent].remove(leaf)
                
                if len(children_of[parent]) == 0:
                    next_leaves.add(parent)
        
        leaves = next_leaves
    
    return {
        'edge_capacities': edge_capacity,
        'segment_losses': segment_losses,
        'total_losses_kw': sum(segment_losses.values()),
        'transformer_requirement': required.get(transformer_name, 0.0)
    }
