"""
Heat Network Loss Calculator

Functions for calculating heat losses in HQ (high-quality) and LQ (low-quality)
heat distribution networks using a branch-collapsing algorithm.
"""

import networkx as nx

from functions.results_processing.extract_model_data import (
    build_demand_lookup,
    get_tech_metadata,
    get_all_nodes
)


def calculate_heat_network_losses(
    df_capacity_coords,
    model,
    buildings_gdf,
    distance_factors,
    heat_loss_rates,
    substation_efficiency=0.9
):
    """
    Calculate heat losses in HQ and LQ networks using branch-collapsing algorithm.
    
    This function builds separate network graphs for the HQ (geothermal to substation)
    and LQ (substation to demand) heat networks, then calculates losses by collapsing
    branches from leaves to roots.
    
    Parameters
    ----------
    df_capacity_coords : pandas.DataFrame
        DataFrame with flow capacities and coordinates from model.
    model : calliope.Model
        Solved Calliope model.
    buildings_gdf : geopandas.GeoDataFrame
        GeoDataFrame with building heat demand data.
    distance_factors : dict
        Multiplication factors for distances by segment type.
    heat_loss_rates : dict
        Heat loss rates in W/m for each pipe type.
        Keys: 'Heat transmission main', 'LQ heat distribution main', 
              'LQ heat distribution secondary'
    substation_efficiency : float, optional
        Heat substation efficiency for HQ→LQ conversion (default: 0.9).
    
    Returns
    -------
    dict
        Dictionary containing:
        - 'adjusted_capacities': dict of tech -> adjusted capacity in kW
        - 'total_LQ_losses_kw': total LQ network losses
        - 'total_HQ_losses_kw': total HQ network losses
        - 'substation_efficiency_losses_kw': losses from substation conversion
        - 'total_system_losses_kw': sum of all heat losses
        - 'supply_losses': dict of supply_node -> additional kW needed
        - 'geothermal_requirement': total kW required from geothermal source
    """
    tech_names, tech_distances = get_tech_metadata(model)
    all_nodes = get_all_nodes(model)
    demand_lookup = build_demand_lookup(buildings_gdf)
    
    # Initialize results
    adjusted_capacities = {}
    supply_losses = {}
    
    # Initialize capacities with original values
    for idx, row in df_capacity_coords.iterrows():
        if '_to_' in str(row['techs']):
            adjusted_capacities[row['techs']] = row['Flow capacity (kW)']
    
    # Separate heat links by carrier type
    df_links = df_capacity_coords[
        df_capacity_coords['carriers'].str.contains('heat', case=False, na=False)
    ].copy()
    
    df_links_HQ = df_links[df_links['carriers'] == 'HQ_heat'].copy()
    df_links_LQ = df_links[df_links['carriers'] == 'LQ_heat'].copy()
    
    # Build LQ network graph
    G_LQ = _build_heat_network_graph(
        df_links_LQ, tech_names, tech_distances, 
        distance_factors, heat_loss_rates, carrier_suffix='LQ_heat'
    )
    
    # Build HQ network graph
    G_HQ = _build_heat_network_graph(
        df_links_HQ, tech_names, tech_distances,
        distance_factors, heat_loss_rates, carrier_suffix='HQ_heat'
    )
    
    # Process LQ network (substation -> demand)
    substation_name = _find_node_by_pattern(all_nodes, 'substation')
    lq_results = _process_network_losses(
        G_LQ, substation_name, demand_lookup, all_nodes
    )
    
    total_LQ_losses_kw = lq_results['total_losses_kw']
    substation_total_demand = lq_results['root_requirement']
    
    # Update adjusted capacities with LQ results
    for tech, capacity in lq_results['edge_capacities'].items():
        adjusted_capacities[tech] = capacity
    
    if substation_name:
        supply_losses[substation_name] = total_LQ_losses_kw
    
    # Process HQ network (geothermal -> substation)
    geothermal_name = _find_node_by_pattern(all_nodes, ['geothermie', 'geothermal'])
    
    # Build HQ demand lookup: substation needs LQ output / efficiency
    hq_demand_lookup = {}
    if substation_name and substation_total_demand > 0:
        hq_demand_lookup[substation_name] = substation_total_demand / substation_efficiency
    
    hq_results = _process_network_losses(
        G_HQ, geothermal_name, hq_demand_lookup, all_nodes
    )
    
    total_HQ_losses_kw = hq_results['total_losses_kw']
    geothermal_requirement = hq_results['root_requirement']
    
    # Update adjusted capacities with HQ results
    for tech, capacity in hq_results['edge_capacities'].items():
        adjusted_capacities[tech] = capacity
    
    # Calculate substation efficiency losses
    substation_efficiency_losses_kw = 0.0
    if substation_name and substation_total_demand > 0:
        substation_efficiency_losses_kw = substation_total_demand * (1/substation_efficiency - 1)
    
    # Calculate additional geothermal capacity needed
    if geothermal_name and geothermal_requirement > 0:
        try:
            original_geothermal_kw = float(
                model.results.flow_out.sel(techs='supply_geothermal').sum()
            )
        except (KeyError, ValueError):
            original_geothermal_kw = 0.0
        
        additional_geothermal_kw = geothermal_requirement - original_geothermal_kw
        supply_losses[geothermal_name] = additional_geothermal_kw
    
    # Store substation adjustment for later use
    if substation_name:
        adjusted_capacities[f'_substation_adjustment_{substation_name}'] = substation_total_demand
    
    total_system_losses_kw = total_LQ_losses_kw + total_HQ_losses_kw + substation_efficiency_losses_kw
    
    return {
        'adjusted_capacities': adjusted_capacities,
        'total_LQ_losses_kw': total_LQ_losses_kw,
        'total_HQ_losses_kw': total_HQ_losses_kw,
        'substation_efficiency_losses_kw': substation_efficiency_losses_kw,
        'total_system_losses_kw': total_system_losses_kw,
        'supply_losses': supply_losses,
        'geothermal_requirement': geothermal_requirement
    }


def _build_heat_network_graph(df_links, tech_names, tech_distances, 
                               distance_factors, heat_loss_rates, carrier_suffix):
    """
    Build a directed graph representing a heat network.
    
    Parameters
    ----------
    df_links : pandas.DataFrame
        DataFrame with link data for this carrier type.
    tech_names : pandas.Series
        Technology names indexed by tech identifier.
    tech_distances : pandas.Series
        Technology distances indexed by tech identifier.
    distance_factors : dict
        Distance multiplication factors by segment type.
    heat_loss_rates : dict
        Heat loss rates in W/m by segment type.
    carrier_suffix : str
        Carrier suffix to strip from node names (e.g., 'LQ_heat', 'HQ_heat').
    
    Returns
    -------
    networkx.DiGraph
        Directed graph with edge attributes for loss calculations.
    """
    G = nx.DiGraph()
    
    for idx, row in df_links.iterrows():
        parts = row['techs'].rsplit('_to_', 1)
        if len(parts) != 2:
            continue
            
        link_from_carrier, link_to_carrier = parts
        link_from = link_from_carrier.replace(f'_{carrier_suffix}', '').replace('_heat', '')
        link_to = link_to_carrier.replace(f'_{carrier_suffix}', '').replace('_heat', '')
        
        tech_name = tech_names.get(row['techs'], 'Unknown')
        distance_km = tech_distances.get(row['techs'], 0)
        distance_m = distance_km * 1000 * distance_factors.get(tech_name, 1.0)
        loss_rate = heat_loss_rates.get(tech_name, 0.0)
        
        # Heat flows FROM link_to TO link_from (reversed for energy flow)
        G.add_edge(
            link_to,
            link_from,
            tech=row['techs'],
            tech_name=tech_name,
            capacity_kw=row['Flow capacity (kW)'],
            distance_m=distance_m,
            loss_rate_w_per_m=loss_rate
        )
    
    return G


def _find_node_by_pattern(all_nodes, patterns):
    """
    Find a node matching one of the given patterns.
    
    Parameters
    ----------
    all_nodes : list
        List of all node names.
    patterns : str or list
        Pattern(s) to search for (case-insensitive substring match).
    
    Returns
    -------
    str or None
        First matching node name, or None if not found.
    """
    if isinstance(patterns, str):
        patterns = [patterns]
    
    for node in all_nodes:
        node_lower = str(node).lower()
        for pattern in patterns:
            if pattern.lower() in node_lower:
                return str(node)
    return None


def _process_network_losses(G, root_name, demand_lookup, all_nodes):
    """
    Process network losses using branch-collapsing algorithm.
    
    Starting from leaf nodes, propagate demand + losses back to root.
    
    Parameters
    ----------
    G : networkx.DiGraph
        Network graph with edge attributes.
    root_name : str or None
        Name of the root node (supply point).
    demand_lookup : dict
        Mapping of node names to demand in kW.
    all_nodes : list
        List of all node names in the model.
    
    Returns
    -------
    dict
        Dictionary containing:
        - 'edge_capacities': dict of tech -> required capacity
        - 'segment_losses': dict of tech -> loss in kW
        - 'total_losses_kw': sum of all segment losses
        - 'root_requirement': total kW required at root node
    """
    result = {
        'edge_capacities': {},
        'segment_losses': {},
        'total_losses_kw': 0.0,
        'root_requirement': 0.0
    }
    
    if not root_name or G.number_of_edges() == 0:
        return result
    
    # Build undirected edge mapping
    edges_undirected = {}
    for u, v, data in G.edges(data=True):
        key = tuple(sorted([u, v]))
        if key not in edges_undirected:
            edges_undirected[key] = {
                'tech': data['tech'],
                'loss_kw': (data['loss_rate_w_per_m'] * data['distance_m']) / 1000.0
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
    
    if root_name not in neighbors:
        return result
    
    # BFS from root to build tree relationships
    parent_of = {}
    children_of = {}
    edge_to_parent = {}
    
    visited = set()
    queue = [root_name]
    visited.add(root_name)
    children_of[root_name] = []
    
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
    
    # Initialize required[node] = demand if demand node, else 0
    required = {}
    for node in visited:
        required[node] = demand_lookup.get(node, 0.0)
    
    # Find initial leaves (nodes with no children)
    leaves = set()
    for node in visited:
        if len(children_of[node]) == 0:
            leaves.add(node)
    
    # Collapse branches
    edge_capacity = {}
    segment_losses = {}
    
    while leaves:
        next_leaves = set()
        
        for leaf in leaves:
            if leaf in parent_of:
                parent = parent_of[leaf]
                edge = edge_to_parent[leaf]
                tech = edge['tech']
                edge_loss = edge['loss_kw']
                
                # Edge capacity = what leaf needs + edge's own loss
                edge_capacity[tech] = required[leaf] + edge_loss
                segment_losses[tech] = edge_loss
                
                # Propagate to parent
                required[parent] = required.get(parent, 0.0) + edge_capacity[tech]
                
                # Remove leaf from parent's children
                children_of[parent].remove(leaf)
                
                # If parent has no more children, it becomes a leaf
                if len(children_of[parent]) == 0:
                    next_leaves.add(parent)
        
        leaves = next_leaves
    
    result['edge_capacities'] = edge_capacity
    result['segment_losses'] = segment_losses
    result['total_losses_kw'] = sum(segment_losses.values())
    result['root_requirement'] = required.get(root_name, 0.0)
    
    return result
