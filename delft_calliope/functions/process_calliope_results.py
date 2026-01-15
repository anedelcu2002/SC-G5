import pandas as pd
import numpy as np
import os
import folium
import geopandas as gpd
import networkx as nx

def process_calliope_results(
    model,
    buildings_gdf,
    mode='plot',
    output_folder='outputs',
    heat_capacity=4.19,
    density=1000,
    delta_T=25,
    flow_speed=0.62,
    distance_factors=None,
    pipe_sizing_method='class',
    heat_loss_rates=None,
    apply_heat_losses=False,
    electricity_resistance_rates=None,
    apply_electricity_losses=False
):
    """
    Process Calliope model results, create visualizations, and export bill of materials.
    
    Parameters:
    -----------
    model : calliope.Model
        Solved Calliope model with results
    buildings_gdf : gpd.GeoDataFrame
        GeoDataFrame with building geometries and heat demand data (must contain 'id', 'Peak heat demand (kW)', and geometry columns)
    mode : str, optional
        Run mode: 'plot' to generate visualization, 'export' to skip visualization (default: 'plot')
    output_folder : str, optional
        Folder to save output files (default: 'outputs')
    heat_capacity : float, optional
        Heat capacity in kJ/kgK for pipe sizing (default: 4.19)
    density : float, optional
        Density in kg/m3 for pipe sizing (default: 1000)
    delta_T : float, optional
        Temperature difference in K for pipe sizing (default: 25)
    flow_speed : float, optional
        Flow speed in m/s for pipe sizing (default: 0.62)
    distance_factors : dict, optional
        Multiplication factors for distances by segment type (default: all 1.0)
        Keys: 'Heat transmission main', 'LQ heat distribution main', 
              'LQ heat distribution secondary', 'LV electricity distribution main',
              'LV electricity distribution secondary'
    pipe_sizing_method : str, optional
        Method for calculating pipe diameters (default: 'class')
        - 'class': Use maximum diameter within each segment type (all pipes of same type get same diameter)
        - 'individual': Round each pipe diameter individually to nearest 5mm
    heat_loss_rates : dict, optional
        Heat loss rates in W/m for each pipe type (default: None, no losses applied)
        Keys: 'Heat transmission main', 'LQ heat distribution main', 'LQ heat distribution secondary'
        Example: {'Heat transmission main': 20, 'LQ heat distribution main': 15, 'LQ heat distribution secondary': 10}
    apply_heat_losses : bool, optional
        Whether to apply heat losses and recalculate required capacities (default: False)
    electricity_resistance_rates : dict, optional
            Resistance values in Ohms/km for each cable type (default: None, no losses applied)
            Keys: 'LV electricity distribution main', 'LV electricity distribution secondary'
            Example: {'LV electricity distribution main': 0.247, 'LV electricity distribution secondary': 0.247}
    apply_electricity_losses : bool, optional
        Whether to apply electricity I²R losses and recalculate required capacities (default: False)
        
    Returns:
    --------
    pd.DataFrame
        Bill of materials DataFrame with capacity, distances, and pipe diameters
    
    Side Effects:
    -------------
    - If mode=='plot', saves system_map.html to output_folder/
    - Saves bill_of_materials.csv to output_folder/
    """
    
    # Default distance factors if not provided
    if distance_factors is None:
        distance_factors = {
            'Heat transmission main': 1.0,
            'LQ heat distribution main': 1.0,
            'LQ heat distribution secondary': 1.0,
            'LV electricity distribution main': 1.0,
            'LV electricity distribution secondary': 1.0
        }
    
    # Default heat loss rates if applying losses
    if apply_heat_losses and heat_loss_rates is None:
        heat_loss_rates = {
            'Heat transmission main': 20.0,      # W/m
            'LQ heat distribution main': 15.0,   # W/m
            'LQ heat distribution secondary': 10.0  # W/m
        }

    # Default electricity resistance rates if applying losses
    if apply_electricity_losses and electricity_resistance_rates is None:
        electricity_resistance_rates = {
            'LV electricity distribution main': 0.247,       # Ω/km
            'LV electricity distribution secondary': 0.247   # Ω/km
        }
    
    # --- 1. Extract coordinates and flow capacities from model ---
    df_coords = model.inputs[["latitude", "longitude"]].to_dataframe().reset_index()
    
    df_capacity = (
        model.results.flow_cap.where(model.inputs.base_tech == "transmission")
        .to_series()
        .where(lambda x: x != 0)
        .dropna()
        .to_frame("Flow capacity (kW)")
        .reset_index()
    )
    
    # Merge coordinates with capacity data
    df_capacity_coords = pd.merge(df_coords, df_capacity, left_on="nodes", right_on="nodes").sort_values(by=['techs'])
    
    # --- Heat loss calculations (if applicable) ---

    total_system_losses_kw = 0.0
    total_LQ_losses_kw = 0.0     
    total_HQ_losses_kw = 0.0      
    total_LV_losses_kw = 0.0      
    supply_losses = {} 
    adjusted_capacities = {}
    
    if apply_heat_losses and heat_loss_rates is not None:
        #print("\n" + "="*60)
        #print("HEAT LOSS CALCULATION - TWO-TIER NETWORK")
        #print("="*60)
        #print(f"apply_heat_losses = {apply_heat_losses}")
        #print(f"heat_loss_rates = {heat_loss_rates}")
        
        # Build SEPARATE network graphs for HQ and LQ heat networks
        G_HQ = nx.DiGraph()  # Geothermal -> warmtenet -> substation
        G_LQ = nx.DiGraph()  # Substation -> LQHtransmission -> demand
        
        # Extract link information
        #print(f"\n1. Extracting heat links from capacity data...")
        #print(f"   Total capacity coords entries: {len(df_capacity_coords)}")
        
        df_links = df_capacity_coords[df_capacity_coords['carriers'].str.contains('heat', case=False, na=False)].copy()
        #print(f"   Heat links found: {len(df_links)}")
        #print(f"   Carrier types: {df_links['carriers'].unique()}")
        
        # Separate HQ and LQ links
        df_links_HQ = df_links[df_links['carriers'] == 'HQ_heat'].copy()
        df_links_LQ = df_links[df_links['carriers'] == 'LQ_heat'].copy()
        #print(f"   HQ_heat links: {len(df_links_HQ)}")
        #print(f"   LQ_heat links: {len(df_links_LQ)}")
        
        # Parse link names
        #print(f"\n2. Building network graphs...")
        tech_names = model.inputs.name.to_series().dropna()
        tech_distances = model.inputs.distance.to_series().dropna()
        
        # Build LQ heat network (substation -> demand)
        #print(f"   2a. Building LQ heat network...")
        for idx, row in df_links_LQ.iterrows():
            # Parse link
            parts = row['techs'].rsplit('_to_', 1)
            if len(parts) == 2:
                link_from_carrier, link_to_carrier = parts
                link_from = link_from_carrier.replace('_LQ_heat', '')
                link_to = link_to_carrier.replace('_LQ_heat', '').replace('_heat', '')
                
                tech_name = tech_names.get(row['techs'], 'Unknown')
                distance_km = tech_distances.get(row['techs'], 0)
                distance_m = distance_km * 1000 * distance_factors.get(tech_name, 1.0)
                loss_rate = heat_loss_rates.get(tech_name, 0.0)
                
                # Heat flows FROM link_to TO link_from (reversed for energy flow)
                G_LQ.add_edge(
                    link_to,
                    link_from,
                    tech=row['techs'],
                    tech_name=tech_name,
                    capacity_kw=row['Flow capacity (kW)'],
                    distance_m=distance_m,
                    loss_rate_w_per_m=loss_rate
                )
        
        #print(f"      LQ network: {G_LQ.number_of_edges()} edges, {G_LQ.number_of_nodes()} nodes")
        
        # Build HQ heat network (geothermal -> warmtenet -> substation)
        #print(f"   2b. Building HQ heat network...")
        for idx, row in df_links_HQ.iterrows():
            # Parse link
            parts = row['techs'].rsplit('_to_', 1)
            if len(parts) == 2:
                link_from_carrier, link_to_carrier = parts
                link_from = link_from_carrier.replace('_HQ_heat', '')
                link_to = link_to_carrier.replace('_HQ_heat', '').replace('_heat', '')
                
                tech_name = tech_names.get(row['techs'], 'Unknown')
                distance_km = tech_distances.get(row['techs'], 0)
                distance_m = distance_km * 1000 * distance_factors.get(tech_name, 1.0)
                loss_rate = heat_loss_rates.get(tech_name, 0.0)
                
                # Heat flows FROM link_to TO link_from (reversed for energy flow)
                G_HQ.add_edge(
                    link_to,
                    link_from,
                    tech=row['techs'],
                    tech_name=tech_name,
                    capacity_kw=row['Flow capacity (kW)'],
                    distance_m=distance_m,
                    loss_rate_w_per_m=loss_rate
                )
        
        #print(f"      HQ network: {G_HQ.number_of_edges()} edges, {G_HQ.number_of_nodes()} nodes")
        
        # ================================================================
        # BRANCH COLLAPSING ALGORITHM FOR HEAT LOSSES
        # ================================================================
        
        all_nodes = model.inputs.coords['nodes'].values if 'nodes' in model.inputs.coords else []
        
        # Initialize adjusted capacities with original values
        for idx, row in df_capacity_coords.iterrows():
            if '_to_' in str(row['techs']):
                adjusted_capacities[row['techs']] = row['Flow capacity (kW)']
        
        # Build demand lookup from buildings_gdf
        #print(f"\n3. Building demand lookup from buildings_gdf...")
        demand_lookup = {}
        for idx, row in buildings_gdf.iterrows():
            building_id = str(row['id'])
            numeric_part = ''.join(filter(str.isdigit, building_id))
            if numeric_part:
                demand_node_id = f"D{numeric_part}"
                demand_lookup[demand_node_id] = row['Peak heat demand (kW)']
        #print(f"   Loaded demands for {len(demand_lookup)} buildings")
        

        # ----------------------------------------------------------------
        # LQ NETWORK
        # ----------------------------------------------------------------
        #print(f"\n4. Processing LQ network with branch collapsing...")
        
        # Build an UNDIRECTED graph first, then create tree by BFS from root
        edges_undirected = {}  # (nodeA, nodeB) -> edge data (sorted tuple as key)
        
        for u, v, data in G_LQ.edges(data=True):
            key = tuple(sorted([u, v]))
            if key not in edges_undirected:
                edges_undirected[key] = {
                    'tech': data['tech'],
                    'loss_kw': (data['loss_rate_w_per_m'] * data['distance_m']) / 1000.0
                }
        
        #print(f"   Unique undirected edges: {len(edges_undirected)}")
        
        # Build adjacency list
        neighbors = {}
        for (a, b), data in edges_undirected.items():
            if a not in neighbors:
                neighbors[a] = []
            if b not in neighbors:
                neighbors[b] = []
            neighbors[a].append((b, data))
            neighbors[b].append((a, data))
        
        # Find substation (root)
        substation_name = None
        for node in all_nodes:
            if 'substation' in str(node).lower():
                substation_name = str(node)
                break
        
        if not substation_name or substation_name not in neighbors:
            substation_name = None
            substation_total_demand = 0.0
        else:
            # BFS from substation to build tree relationships
            parent_of = {}      # child -> parent
            children_of = {}    # parent -> [children]
            edge_to_parent = {} # child -> edge data
            
            visited = set()
            queue = [substation_name]
            visited.add(substation_name)
            children_of[substation_name] = []
            
            while queue:
                current = queue.pop(0)
                
                for neighbor, edge_data in neighbors.get(current, []):
                    if neighbor not in visited:
                        visited.add(neighbor)
                        
                        # current is parent, neighbor is child
                        parent_of[neighbor] = current
                        edge_to_parent[neighbor] = edge_data
                        
                        if current not in children_of:
                            children_of[current] = []
                        children_of[current].append(neighbor)
                        
                        if neighbor not in children_of:
                            children_of[neighbor] = []
                        
                        queue.append(neighbor)
            
            #print(f"   BFS visited {len(visited)} nodes from substation")
            
            # Initialize required[node] = demand if demand node, else 0
            required = {}
            for node in visited:
                required[node] = demand_lookup.get(node, 0.0)
            
            # Find initial leaves (nodes with no children)
            leaves = set()
            for node in visited:
                if len(children_of[node]) == 0:
                    leaves.add(node)
            
            #print(f"   Initial leaves: {len(leaves)}")
            
            # Collapse branches
            edge_capacity_LQ = {}
            segment_losses_LQ = {}
            
            while leaves:
                next_leaves = set()
                
                for leaf in leaves:
                    if leaf in parent_of:
                        parent = parent_of[leaf]
                        edge = edge_to_parent[leaf]
                        tech = edge['tech']
                        edge_loss = edge['loss_kw']
                        
                        # Edge capacity = what leaf needs + edge's own loss
                        edge_capacity_LQ[tech] = required[leaf] + edge_loss
                        segment_losses_LQ[tech] = edge_loss
                        
                        # Propagate to parent
                        required[parent] = required.get(parent, 0.0) + edge_capacity_LQ[tech]
                        
                        # Remove leaf from parent's children
                        children_of[parent].remove(leaf)
                        
                        # If parent has no more children, it becomes a leaf
                        if len(children_of[parent]) == 0:
                            next_leaves.add(parent)
                
                leaves = next_leaves
            
            # Apply LQ capacities
            total_LQ_losses_kw = sum(segment_losses_LQ.values())
            for tech, capacity in edge_capacity_LQ.items():
                adjusted_capacities[tech] = capacity
            
            substation_total_demand = required.get(substation_name, 0.0)
            #print(f"   LQ losses: {total_LQ_losses_kw:.2f} kW across {len(segment_losses_LQ)} segments")
            supply_losses[substation_name] = total_LQ_losses_kw
            #print(f"   Substation '{substation_name}' total requirement: {substation_total_demand:.2f} kW")

        # ----------------------------------------------------------------
        # HQ NETWORK
        # ----------------------------------------------------------------
        #print(f"\n5. Processing HQ network with branch collapsing...")
        
        # Build an UNDIRECTED graph first, then create tree by BFS from root
        edges_undirected_HQ = {}  # (nodeA, nodeB) -> edge data (sorted tuple as key)
        
        for u, v, data in G_HQ.edges(data=True):
            key = tuple(sorted([u, v]))
            if key not in edges_undirected_HQ:
                edges_undirected_HQ[key] = {
                    'tech': data['tech'],
                    'loss_kw': (data['loss_rate_w_per_m'] * data['distance_m']) / 1000.0
                }
        
        #print(f"   Unique undirected edges: {len(edges_undirected_HQ)}")
        
        # Build adjacency list
        neighbors_HQ = {}
        for (a, b), data in edges_undirected_HQ.items():
            if a not in neighbors_HQ:
                neighbors_HQ[a] = []
            if b not in neighbors_HQ:
                neighbors_HQ[b] = []
            neighbors_HQ[a].append((b, data))
            neighbors_HQ[b].append((a, data))
        
        # Find geothermal node (root of HQ network)
        geothermal_name = None
        for node in all_nodes:
            if 'geothermie' in str(node).lower() or 'geothermal' in str(node).lower():
                geothermal_name = str(node)
                break
        
        if not geothermal_name or geothermal_name not in neighbors_HQ:
            total_HQ_losses_kw = 0.0
        else:
            # BFS from geothermal to build tree relationships
            parent_of_HQ = {}      # child -> parent
            children_of_HQ = {}    # parent -> [children]
            edge_to_parent_HQ = {} # child -> edge data
            
            visited_HQ = set()
            queue_HQ = [geothermal_name]
            visited_HQ.add(geothermal_name)
            children_of_HQ[geothermal_name] = []
            
            while queue_HQ:
                current = queue_HQ.pop(0)
                
                for neighbor, edge_data in neighbors_HQ.get(current, []):
                    if neighbor not in visited_HQ:
                        visited_HQ.add(neighbor)
                        
                        # current is parent, neighbor is child
                        parent_of_HQ[neighbor] = current
                        edge_to_parent_HQ[neighbor] = edge_data
                        
                        if current not in children_of_HQ:
                            children_of_HQ[current] = []
                        children_of_HQ[current].append(neighbor)
                        
                        if neighbor not in children_of_HQ:
                            children_of_HQ[neighbor] = []
                        
                        queue_HQ.append(neighbor)
            
            #print(f"   BFS visited {len(visited_HQ)} nodes from geothermal")
            
            # Initialize required_HQ[node] - substation is the demand point
            required_HQ = {}
            for node in visited_HQ:
                if substation_name and node == substation_name:
                    required_HQ[node] = substation_total_demand
                else:
                    required_HQ[node] = 0.0
            
            # Find initial leaves (nodes with no children)
            leaves_HQ = set()
            for node in visited_HQ:
                if len(children_of_HQ[node]) == 0:
                    leaves_HQ.add(node)
            
            #print(f"   Initial leaves: {len(leaves_HQ)}")
            
            # Collapse branches
            edge_capacity_HQ = {}
            segment_losses_HQ = {}
            
            while leaves_HQ:
                next_leaves = set()
                
                for leaf in leaves_HQ:
                    if leaf in parent_of_HQ:
                        parent = parent_of_HQ[leaf]
                        edge = edge_to_parent_HQ[leaf]
                        tech = edge['tech']
                        edge_loss = edge['loss_kw']
                        
                        # Edge capacity = what leaf needs + edge's own loss
                        edge_capacity_HQ[tech] = required_HQ[leaf] + edge_loss
                        segment_losses_HQ[tech] = edge_loss
                        
                        # Propagate to parent
                        required_HQ[parent] = required_HQ.get(parent, 0.0) + edge_capacity_HQ[tech]
                        
                        # Remove leaf from parent's children
                        children_of_HQ[parent].remove(leaf)
                        
                        # If parent has no more children, it becomes a leaf
                        if len(children_of_HQ[parent]) == 0:
                            next_leaves.add(parent)
                
                leaves_HQ = next_leaves
            
            # Apply HQ capacities
            total_HQ_losses_kw = sum(segment_losses_HQ.values())
            for tech, capacity in edge_capacity_HQ.items():
                adjusted_capacities[tech] = capacity
            
            geothermal_requirement = required_HQ.get(geothermal_name, 0.0)
            #print(f"   HQ losses: {total_HQ_losses_kw:.2f} kW across {len(segment_losses_HQ)} segments")
            #print(f"   Geothermal '{geothermal_name}' total requirement: {geothermal_requirement:.2f} kW")
        
        total_system_losses_kw = total_LQ_losses_kw + total_HQ_losses_kw
        
        if geothermal_name:
            supply_losses[geothermal_name] = total_system_losses_kw
        
        #print(f"\n" + "="*60)
        #print(f"SUMMARY:")
        #print(f"  Total building demand: {sum(demand_lookup.values()):.2f} kW")
        #print(f"  LQ network losses: {total_LQ_losses_kw:.2f} kW ({len(segment_losses_LQ)} segments)")
        #print(f"  HQ network losses: {total_HQ_losses_kw:.2f} kW ({len(segment_losses_HQ)} segments)")
        #print(f"  Total system losses: {total_system_losses_kw:.2f} kW")
        #print("="*60 + "\n")

    # ================================================================
    # LV ELECTRICITY NETWORK LOSS ALGORITHM (MULTI-CLUSTER)
    # Loss = I² × R × distance, where I = P / V
    # V = 400V (line voltage), R from electricity_resistance_rates (Ω/km)
    # ================================================================

    LV_VOLTAGE = 400  # Volts
    total_LV_losses_kw = 0.0

    if apply_electricity_losses and electricity_resistance_rates is not None:
        # Build LV electricity network graph
        G_LV = nx.DiGraph()
        
        # Separate electricity links
        df_links_elec = df_capacity_coords[
            df_capacity_coords['carriers'].str.contains('electricity', case=False, na=False)
        ].copy()
        
        # Build the electricity network graph
        for idx, row in df_links_elec.iterrows():
            parts = row['techs'].rsplit('_to_', 1)
            if len(parts) == 2:
                link_from_carrier, link_to_carrier = parts
                link_from = link_from_carrier.replace('_electricity', '')
                link_to = link_to_carrier.replace('_electricity', '')
                
                tech_name = tech_names.get(row['techs'], 'Unknown')
                distance_km = tech_distances.get(row['techs'], 0)
                distance_km_adjusted = distance_km * distance_factors.get(tech_name, 1.0)
                resistance_per_km = electricity_resistance_rates.get(tech_name, 0.0)
                
                G_LV.add_edge(
                    link_to,
                    link_from,
                    tech=row['techs'],
                    tech_name=tech_name,
                    capacity_kw=row['Flow capacity (kW)'],
                    distance_km=distance_km_adjusted,
                    resistance_per_km=resistance_per_km
                )
        
        # Build undirected edge mapping
        edges_undirected_LV = {}
        for u, v, data in G_LV.edges(data=True):
            key = tuple(sorted([u, v]))
            if key not in edges_undirected_LV:
                edges_undirected_LV[key] = {
                    'tech': data['tech'],
                    'distance_km': data['distance_km'],
                    'resistance_per_km': data['resistance_per_km']
                }
        
        # Build adjacency list
        neighbors_LV = {}
        for (a, b), data in edges_undirected_LV.items():
            if a not in neighbors_LV:
                neighbors_LV[a] = []
            if b not in neighbors_LV:
                neighbors_LV[b] = []
            neighbors_LV[a].append((b, data))
            neighbors_LV[b].append((a, data))
        
        # ============================================================
        # NEW: Find ALL transformer nodes (roots of each cluster)
        # ============================================================
        transformer_nodes = []
        for node in all_nodes:
            node_str = str(node)
            if ('transformer' in node_str.lower() or 'trafo' in node_str.lower()) and node_str in neighbors_LV:
                transformer_nodes.append(node_str)
        
        # ============================================================
        # NEW: Build electricity demand lookup from heat pump flow_in
        # ============================================================
        elec_demand_lookup = {}
        
        # Check if heat_pump tech exists in the model first
        if 'heat_pump' in model.inputs.coords.get('techs', []):
            try:
                heat_pump_flow_in = (
                    model.results.flow_cap
                    .sel(techs='heat_pump', carriers='electricity')
                    .to_series()
                    .dropna()
                )
                
                for node, capacity in heat_pump_flow_in.items():
                    if capacity > 0:
                        elec_demand_lookup[str(node)] = abs(float(capacity))
                        
            except (KeyError, ValueError):
                # Try alternative method: flow_in instead of flow_cap
                try:
                    heat_pump_flow_in = (
                        model.results.flow_in
                        .sel(techs='heat_pump', carriers='electricity')
                        .max(dim='timesteps')
                        .to_series()
                        .dropna()
                    )
                    
                    for node, demand in heat_pump_flow_in.items():
                        if demand > 0:
                            elec_demand_lookup[str(node)] = abs(float(demand))
                            
                except (KeyError, ValueError):
                    pass  # No heat pump data available, leave elec_demand_lookup empty
        
        # ============================================================
        # NEW: Process EACH transformer cluster independently
        # ============================================================
        all_segment_losses_LV = {}
        all_edge_capacity_LV = {}
        
        for transformer_name in transformer_nodes:
            # BFS from this transformer to build tree relationships
            parent_of_LV = {}
            children_of_LV = {}
            edge_to_parent_LV = {}
            
            visited_LV = set()
            queue_LV = [transformer_name]
            visited_LV.add(transformer_name)
            children_of_LV[transformer_name] = []
            
            while queue_LV:
                current = queue_LV.pop(0)
                
                for neighbor, edge_data in neighbors_LV.get(current, []):
                    if neighbor not in visited_LV:
                        visited_LV.add(neighbor)
                        
                        parent_of_LV[neighbor] = current
                        edge_to_parent_LV[neighbor] = edge_data
                        
                        if current not in children_of_LV:
                            children_of_LV[current] = []
                        children_of_LV[current].append(neighbor)
                        
                        if neighbor not in children_of_LV:
                            children_of_LV[neighbor] = []
                        
                        queue_LV.append(neighbor)
            
            # Initialize required power at each node in this cluster
            required_LV = {}
            for node in visited_LV:
                required_LV[node] = elec_demand_lookup.get(node, 0.0)
            
            # Find initial leaves (nodes with no children)
            leaves_LV = set()
            for node in visited_LV:
                if len(children_of_LV[node]) == 0:
                    leaves_LV.add(node)
            
            # Collapse branches with I²R loss calculation
            edge_capacity_LV = {}
            segment_losses_LV = {}
            
            while leaves_LV:
                next_leaves = set()
                
                for leaf in leaves_LV:
                    if leaf in parent_of_LV:
                        parent = parent_of_LV[leaf]
                        edge = edge_to_parent_LV[leaf]
                        tech = edge['tech']
                        distance_km = edge['distance_km']
                        resistance_per_km = edge['resistance_per_km']
                        
                        # Power flowing through this edge
                        power_kw = required_LV[leaf]
                        
                        # I²R loss calculation
                        power_w = power_kw * 1000
                        current_a = power_w / LV_VOLTAGE
                        resistance_ohms = resistance_per_km * distance_km
                        loss_w = (current_a ** 2) * resistance_ohms
                        edge_loss_kw = loss_w / 1000
                        
                        # Edge capacity = demand + loss
                        edge_capacity_LV[tech] = power_kw + edge_loss_kw
                        segment_losses_LV[tech] = edge_loss_kw
                        
                        # Propagate to parent
                        required_LV[parent] = required_LV.get(parent, 0.0) + edge_capacity_LV[tech]
                        
                        children_of_LV[parent].remove(leaf)
                        
                        if len(children_of_LV[parent]) == 0:
                            next_leaves.add(parent)
                
                leaves_LV = next_leaves
            
            # Store results for this cluster
            cluster_losses = sum(segment_losses_LV.values())
            all_segment_losses_LV.update(segment_losses_LV)
            all_edge_capacity_LV.update(edge_capacity_LV)
            
            # Store transformer demand (for reporting)
            transformer_total_demand = required_LV.get(transformer_name, 0.0)
            supply_losses[transformer_name] = cluster_losses
        
        # ============================================================
        # Aggregate results across all clusters
        # ============================================================
        total_LV_losses_kw = sum(all_segment_losses_LV.values())
        
        for tech, capacity in all_edge_capacity_LV.items():
            adjusted_capacities[tech] = capacity
        
        #print(f"LV electricity losses: {total_LV_losses_kw:.2f} kW across {len(all_segment_losses_LV)} segments")
        #print(f"Processed {len(transformer_nodes)} transformer clusters")


    # --- 2. Visualize results (if mode=='plot') ---
    if mode == 'plot':
        #print("Generating system map visualization...")
        
        # Extract link information from techs column
        df_links = df_capacity_coords.copy()
        
        # Split the techs column to get link_from and link_to
        df_links[['link_from', 'link_to_carrier']] = df_links['techs'].str.rsplit('_to_', n=1, expand=True)
        df_links['link_to'] = df_links['link_to_carrier'].str.replace(r'_(heat|electricity|HQ_heat|LQ_heat)$', '', regex=True)
        df_links['link_from'] = df_links['link_from'].str.replace(r'_(heat|electricity|HQ_heat|LQ_heat)$', '', regex=True)
        
        # Merge with df_coords twice to get both from and to coordinates
        df_links = df_links.merge(
            df_coords[['nodes', 'latitude', 'longitude']],
            left_on='link_from',
            right_on='nodes',
            how='left',
            suffixes=('', '_from')
        )
        df_links = df_links.rename(columns={'latitude': 'lat_from', 'longitude': 'lon_from'})
        
        df_links = df_links.merge(
            df_coords[['nodes', 'latitude', 'longitude']],
            left_on='link_to',
            right_on='nodes',
            how='left',
            suffixes=('_temp', '_to')
        )
        df_links = df_links.rename(columns={'latitude': 'lat_to', 'longitude': 'lon_to'})
        
        # Clean up duplicate columns
        df_links = df_links.drop(columns=['nodes_temp', 'nodes_to'], errors='ignore')
        
        # Create Folium map
        center_lat = df_coords['latitude'].mean()
        center_lon = df_coords['longitude'].mean()
        map_fig = folium.Map(
            location=[center_lat, center_lon],
            zoom_start=16,
            tiles='OpenStreetMap'
        )
        
        # Create FeatureGroups for different layers
        demand_group = folium.FeatureGroup(name="Demand Nodes", show=True).add_to(map_fig)
        supply_heat_group = folium.FeatureGroup(name="Supply Heat Nodes", show=True).add_to(map_fig)
        supply_elec_group = folium.FeatureGroup(name="Supply Electricity Nodes", show=True).add_to(map_fig)
        transmission_heat_group = folium.FeatureGroup(name="Heat Transmission Nodes", show=True).add_to(map_fig)
        distribution_heat_group = folium.FeatureGroup(name="Heat Distribution Nodes", show=True).add_to(map_fig)
        HQ_heat_link_group = folium.FeatureGroup(name="HQ Heat Links", show=True).add_to(map_fig)
        LQ_heat_link_group = folium.FeatureGroup(name="LQ Heat Links", show=True).add_to(map_fig)
        distribution_electricity_group = folium.FeatureGroup(name="Electricity Distribution Nodes", show=True).add_to(map_fig)
        electricity_link_group = folium.FeatureGroup(name="Electricity Links", show=True).add_to(map_fig)
        substation_group = folium.FeatureGroup(name="Substations", show=True).add_to(map_fig)
        building_group = folium.FeatureGroup(name="Buildings", show=True).add_to(map_fig)
        
        # Add link polylines
        for idx, row in df_links.iterrows():
            if row['carriers'] == 'HQ_heat':
                color = 'red'
                target_group = HQ_heat_link_group
                weight = 4
            elif row['carriers'] == 'LQ_heat':
                color = "#ff5100"
                target_group = LQ_heat_link_group
                weight = 2
            else:
                color = 'blue'
                target_group = electricity_link_group
                weight = 2
            
            # Get adjusted capacity if available
            tech_key = row['techs']
            original_capacity = row['Flow capacity (kW)']
            adjusted_capacity = adjusted_capacities.get(tech_key, original_capacity) if apply_heat_losses else original_capacity
            loss = adjusted_capacity - original_capacity if apply_heat_losses else 0.0
            
            popup_text = f"<b>{row['techs']}</b><br>From: {row['link_from']}<br>To: {row['link_to']}<br>"
            if apply_heat_losses and loss > 0:
                popup_text += f"Original Capacity: {original_capacity:.2f} kW<br>"
                popup_text += f"<b>Adjusted Capacity: {adjusted_capacity:.2f} kW</b><br>"
                popup_text += f"Loss: +{loss:.2f} kW"
            else:
                popup_text += f"Capacity: {original_capacity:.2f} kW"
            
            folium.PolyLine(
                locations=[[row['lat_from'], row['lon_from']], [row['lat_to'], row['lon_to']]],
                color=color,
                weight=weight,
                opacity=1,
                popup=popup_text
            ).add_to(target_group)
        
        # Add node markers
        for idx, row in df_capacity_coords.iterrows():
            node_name = row['nodes']
            
            # Get adjusted capacity for supply nodes
            original_capacity = row['Flow capacity (kW)']
            if apply_heat_losses and node_name in supply_losses:
                adjusted_capacity = original_capacity + supply_losses[node_name]
                loss = supply_losses[node_name]
            else:
                adjusted_capacity = original_capacity
                loss = 0.0
            
            # Determine node type and styling
            if node_name.startswith('geothermie'):
                color = '#2ecc71'
                radius = 5
                node_type = 'Supply heat'
                target_group = supply_heat_group
            elif node_name.startswith('MV'):
                color = "#2e38cc"
                radius = 1
                node_type = 'Supply electricity'
                target_group = supply_elec_group
            elif node_name.startswith('D'):
                color = "#ff9100"
                radius = 3
                node_type = 'Demand'
                target_group = demand_group
            elif node_name.startswith('warmtenet'):
                color = "#94d3ae"
                radius = 1
                node_type = 'Transmission heat'
                target_group = transmission_heat_group
            elif node_name.startswith('LQHtransmission'):
                color = "#94d3ae"
                radius = 1
                node_type = 'Distribution heat'
                target_group = distribution_heat_group
            elif node_name.startswith('substation'):
                color = "#ff3300"
                radius = 3
                node_type = 'Heat substation'
                target_group = substation_group
            else:
                color = "#7076cc"
                radius = 1
                node_type = 'Distribution electricity'
                target_group = distribution_electricity_group
            
            # Build popup text
            popup_text = f"<b>{row['nodes']}</b> ({node_type})<br>"
            if apply_heat_losses and loss > 0:
                popup_text += f"Original Capacity: {original_capacity:.2f} kW<br>"
                popup_text += f"<b>Adjusted Capacity: {adjusted_capacity:.2f} kW</b><br>"
                popup_text += f"Additional supply for losses: +{loss:.2f} kW"
            else:
                popup_text += f"Capacity: {original_capacity:.2f} kW"
            
            folium.CircleMarker(
                location=[row['latitude'], row['longitude']],
                radius=radius,
                popup=popup_text,
                color=color,
                fill=True,
                fillColor=color,
                fillOpacity=1,
                weight=2
            ).add_to(target_group)
        
        # Add building polygons with color based on heat demand
        # Convert buildings_gdf to WGS84 if not already
        if buildings_gdf.crs is not None and buildings_gdf.crs.to_string() != 'EPSG:4326':
            buildings_gdf_wgs84 = buildings_gdf.to_crs(epsg=4326)
        else:
            buildings_gdf_wgs84 = buildings_gdf
        
        max_demand = buildings_gdf['Peak heat demand (kW)'].max()
        min_demand = buildings_gdf['Peak heat demand (kW)'].min()
        
        for idx, row in buildings_gdf_wgs84.iterrows():
            demand = row['Peak heat demand (kW)']
            normalized = (demand - min_demand) / (max_demand - min_demand) if max_demand > min_demand else 0.5
            
            # Color from light yellow (low demand) to dark red (high demand)
            red = int(255)
            green = int(255 * (1 - normalized*0.9))
            blue = int(255 * (1 - normalized*0.9))
            color = f'#{red:02x}{green:02x}{blue:02x}'
            
            folium.GeoJson(
                row.geometry,
                style_function=lambda x, color=color: {
                    'fillColor': color,
                    'color': '#333333',
                    'weight': 1,
                    'fillOpacity': 0.8
                },
                popup=folium.Popup(
                    f"<b>Building ID:</b> {row['id']}<br>"
                    f"<b>Peak Heat Demand:</b> {row['Peak heat demand (kW)']:.2f} kW<br>",
                    max_width=250
                )
            ).add_to(building_group)

        # Add floating statistics box
        # Extract model size from summary
        num_nodes = int(len(model.inputs.coords.get('nodes', [])))
        num_techs = int(len(model.inputs.coords.get('techs', [])))
        num_carriers = int(len(model.inputs.coords.get('carriers', [])))
        num_timesteps = int(len(model.inputs.coords.get('timesteps', [])))
        num_links = int((model.inputs.base_tech == "transmission").sum()) if 'base_tech' in model.inputs else 0
        
        # Build statistics HTML
        stats_html = f"""
        <div style="position: fixed; 
                    bottom: 10px; 
                    left: 10px; 
                    width: 300px; 
                    background-color: white; 
                    border: 2px solid grey; 
                    border-radius: 5px;
                    z-index: 9999; 
                    font-size: 12px;
                    padding: 10px;
                    box-shadow: 0 0 10px rgba(0,0,0,0.3);">
            <h4 style="margin: 0 0 10px 0; color: #333;">Model Statistics</h4>
            <table style="width: 100%; border-collapse: collapse;">
                <tr style="background-color: #f0f0f0;"><td colspan="2" style="padding: 5px; font-weight: bold;">Model Size</td></tr>
                <tr><td style="padding: 3px; padding-left: 10px;">Nodes:</td><td style="text-align: right; padding: 3px;">{num_nodes}</td></tr>
                <tr><td style="padding: 3px; padding-left: 10px;">Links:</td><td style="text-align: right; padding: 3px;">{num_links}</td></tr>
        """
        
        # Add results summary if model is solved
        if hasattr(model, 'results') and len(model.results.data_vars) > 0:
            try:
                stats_html += '<tr style="background-color: #f0f0f0;"><td colspan="2" style="padding: 5px; padding-top: 10px; font-weight: bold;">Results Summary</td></tr>'
                
                 # Initialize variables to track values for efficiency calculation
                geo_cap_original = 0.0
                geo_cap_adjusted = 0.0
                hp_cap = 0.0
                heat_demand = 0.0

                # Supply geothermal capacity
                try:
                    geo_cap_original = float(model.results['flow_out'].sel(techs='supply_geothermal').sum())
                    
                    # Apply losses if calculated
                    if apply_heat_losses and 'geothermie_delft' in supply_losses:
                        geo_cap_adjusted = geo_cap_original + supply_losses['geothermie_delft']
                        stats_html += f'<tr><td style="padding: 3px; padding-left: 10px;">Supply Geothermal:</td><td style="text-align: right; padding: 3px;"><b>{geo_cap_adjusted:,.0f} kW</b></td></tr>'
                        stats_html += f'<tr><td style="padding: 3px; padding-left: 20px; font-size: 10px; color: #666;">Original:</td><td style="text-align: right; padding: 3px; font-size: 10px; color: #666;">{geo_cap_original:,.0f} kW</td></tr>'
                        stats_html += f'<tr><td style="padding: 3px; padding-left: 20px; font-size: 10px; color: #666;">Losses:</td><td style="text-align: right; padding: 3px; font-size: 10px; color: #666;">+{supply_losses["geothermie_delft"]:,.0f} kW</td></tr>'
                    else:
                        geo_cap_adjusted = geo_cap_original
                        stats_html += f'<tr><td style="padding: 3px; padding-left: 10px;">Supply Geothermal:</td><td style="text-align: right; padding: 3px;">{geo_cap_original:,.0f} kW</td></tr>'
                except (KeyError, ValueError):
                    stats_html += f'<tr><td style="padding: 3px; padding-left: 10px;">Supply Geothermal:</td><td style="text-align: right; padding: 3px;">0 kW</td></tr>'
                
                # Heat pump capacity
                try:
                    hp_cap = float(model.results['flow_out'].sel(techs='heat_pump').sum())
                    stats_html += f'<tr><td style="padding: 3px; padding-left: 10px;">Heat Pumps:</td><td style="text-align: right; padding: 3px;">{hp_cap:,.0f} kW</td></tr>'
                except (KeyError, ValueError):
                    stats_html += f'<tr><td style="padding: 3px; padding-left: 10px;">Heat Pumps:</td><td style="text-align: right; padding: 3px;">0 kW</td></tr>'
            
                # Total heat demand
                try:
                    heat_demand = abs(float(model.results['flow_in'].sel(techs='demand_LQ_heat').sum()))
                    stats_html += f'<tr><td style="padding: 3px; padding-left: 10px;">Total Heat Demand:</td><td style="text-align: right; padding: 3px;">{heat_demand:,.0f} kW</td></tr>'
                except (KeyError, ValueError):
                    stats_html += f'<tr><td style="padding: 3px; padding-left: 10px;">Total Heat Demand:</td><td style="text-align: right; padding: 3px;">0 kW</td></tr>'
            
                # Add heat loss information if calculated
                if apply_heat_losses and total_system_losses_kw > 0:
                    stats_html += '<tr style="background-color: #fff3cd;"><td colspan="2" style="padding: 5px; padding-top: 10px; font-weight: bold;">Heat Losses</td></tr>'
                    stats_html += f'<tr><td style="padding: 3px; padding-left: 10px;">Total System Losses:</td><td style="text-align: right; padding: 3px;"><b>{total_system_losses_kw:,.2f} kW</b></td></tr>'
                    
                    # Calculate loss percentage only if not hybrid (both heat pump and geothermal active)
                    is_hybrid = hp_cap > 0 and geo_cap_original > 0
                    if heat_demand > 0 and not is_hybrid:
                        loss_percentage = (total_system_losses_kw / heat_demand) * 100
                        stats_html += f'<tr><td style="padding: 3px; padding-left: 10px;">Loss Percentage:</td><td style="text-align: right; padding: 3px;">{loss_percentage:.1f}%</td></tr>'

                # District heating efficiency (only if heat pump = 0)
                if hp_cap == 0.0 and geo_cap_adjusted > 0:
                    # Efficiency = demand / original supply (before adding capacity for losses)
                    efficiency = heat_demand / geo_cap_adjusted
                    stats_html += f'<tr><td style="padding: 3px; padding-left: 10px;">DH Efficiency:</td><td style="text-align: right; padding: 3px;">{efficiency:.3f}</td></tr>'       
            
                # Add electricity loss information if calculated
                if apply_electricity_losses and total_LV_losses_kw > 0:
                    stats_html += '<tr style="background-color: #cce5ff;"><td colspan="2" style="padding: 5px; padding-top: 10px; font-weight: bold;">Electricity Losses</td></tr>'
                    stats_html += f'<tr><td style="padding: 3px; padding-left: 10px;">Total LV Losses:</td><td style="text-align: right; padding: 3px;"><b>{total_LV_losses_kw:,.2f} kW</b></td></tr>'
                    stats_html += f'<tr><td style="padding: 3px; padding-left: 10px;">Transformer clusters:</td><td style="text-align: right; padding: 3px;">{len(transformer_nodes)}</td></tr>'
                    
                    # Calculate loss percentage only if not hybrid (both heat pump and geothermal active)
                    is_hybrid = hp_cap > 0 and geo_cap_original > 0
                    total_hp_elec_demand = sum(elec_demand_lookup.values())
                    if total_hp_elec_demand > 0 and not is_hybrid:
                        elec_loss_percentage = (total_LV_losses_kw / total_hp_elec_demand) * 100
                        stats_html += f'<tr><td style="padding: 3px; padding-left: 10px;">Loss Percentage:</td><td style="text-align: right; padding: 3px;">{elec_loss_percentage:.1f}%</td></tr>'

            except Exception:
                pass
        
        stats_html += """
            </table>
        </div>
        """
        
        map_fig.get_root().html.add_child(folium.Element(stats_html))

        # Add LayerControl
        folium.LayerControl().add_to(map_fig)
        
        # Save the map
        os.makedirs(output_folder, exist_ok=True)
        map_fig.save(os.path.join(output_folder, 'system_map.html'))
        #print(f" Saved system map to {output_folder}/system_map.html")
    
    # --- 3. Export bill of materials ---
    tech_names = model.inputs.name.to_series().dropna()
    tech_distances = model.inputs.distance.to_series().dropna()
    
    total_flow_out = (
        model.results.flow_out
        .sum(dim=["nodes", "carriers", "timesteps"], min_count=1)
        .to_series()
        .dropna()
    )
    
    # Apply adjusted capacities if losses were calculated
    if (apply_heat_losses or apply_electricity_losses) and len(adjusted_capacities) > 0:
        #print("\n1. Applying loss adjustments to transmission links...")
        
        # Update transmission link capacities
        updated_count = 0
        for tech_idx in total_flow_out.index:
            if tech_idx in adjusted_capacities:
                original = total_flow_out[tech_idx]
                total_flow_out[tech_idx] = adjusted_capacities[tech_idx]
                updated_count += 1
        
        #print(f"   Total transmission links updated: {updated_count}")
        
        # Update supply node capacities
        #print("\n2. Updating supply node capacities...")
        supply_updated = 0
        
        for supply_node, loss_kw in supply_losses.items():
            matched_techs = []
            
            # Check if this is a transformer (electricity network supply)
            if 'transformer' in supply_node.lower() or 'trafo' in supply_node.lower():
                # Look for "Low-voltage electricity supply" or similar
                for tech_idx in total_flow_out.index:
                    tech_str = str(tech_idx).lower()
                    if ('low-voltage' in tech_str or 'low voltage' in tech_str or 'lv' in tech_str) and \
                       'electricity' in tech_str and 'supply' in tech_str:
                        matched_techs.append(tech_idx)
                        
            # Check if this is a geothermal supply (heat network)
            elif 'geotherm' in supply_node.lower():
                # Look for "Geothermal heat supply"
                for tech_idx in total_flow_out.index:
                    tech_str = str(tech_idx).lower()
                    if 'geothermal' in tech_str and 'supply' in tech_str:
                        matched_techs.append(tech_idx)
            
            # Check if this is a heat substation
            elif 'substation' in supply_node.lower():
                # Look for "HQ to LQ heat conversion substation"
                for tech_idx in total_flow_out.index:
                    tech_str = str(tech_idx).lower()
                    if 'substation' in tech_str and ('conversion' in tech_str or 'hq' in tech_str or 'lq' in tech_str):
                        matched_techs.append(tech_idx)
            
            # Apply the loss to matched techs (only once, not per transformer)
            if len(matched_techs) > 0:
                # For transformers, aggregate all losses and apply once
                if 'transformer' in supply_node.lower():
                    # Check if we already updated this tech
                    if matched_techs[0] not in [t for t, _ in locals().get('_updated_techs', [])]:
                        # Aggregate all transformer losses
                        total_transformer_losses = sum(
                            loss for node, loss in supply_losses.items() 
                            if 'transformer' in node.lower()
                        )
                        
                        tech_idx = matched_techs[0]
                        original = total_flow_out[tech_idx]
                        total_flow_out[tech_idx] += total_transformer_losses
                        #print(f"   Updated '{tech_idx}': {original:.2f} -> {total_flow_out[tech_idx]:.2f} kW (+{total_transformer_losses:.2f} kW total LV losses)")
                        supply_updated += 1
                        
                        # Mark as updated to avoid duplicate updates
                        if '_updated_techs' not in locals():
                            _updated_techs = []
                        _updated_techs.append((tech_idx, supply_node))
                else:
                    # For non-transformer supplies, apply individual losses
                    for tech_idx in matched_techs:
                        original = total_flow_out[tech_idx]
                        total_flow_out[tech_idx] += loss_kw
                        #print(f"   Updated '{tech_idx}': {original:.2f} -> {total_flow_out[tech_idx]:.2f} kW (+{loss_kw:.2f} kW)")
                        supply_updated += 1
        
        
    export_df = pd.DataFrame({
        'name': tech_names,
        'capacity_kw': total_flow_out,
        'distance_m': tech_distances * 1000
    })
    
    # Apply distance multiplication factors
    export_df['distance_m'] = export_df.apply(
        lambda row: row['distance_m'] * distance_factors.get(row['name'], 1.0), 
        axis=1
    )
    # Calculate flow rates and pipe diameters (ONLY for heat segments)
    # Identify heat-related segments
    heat_segments = export_df['name'].str.contains('heat|Heat', case=False, na=False)
    
    export_df['flow_rate_m^3/s'] = np.where(
        heat_segments & export_df['capacity_kw'].notnull() & export_df['distance_m'].notnull(),
        export_df['capacity_kw'] / (heat_capacity * density * delta_T),
        np.nan
    )
    
    export_df['diameter_mm'] = np.where(
        heat_segments & export_df['capacity_kw'].notnull() & export_df['distance_m'].notnull(),
        (export_df['flow_rate_m^3/s'] / np.pi / flow_speed * 4)**0.5 * 1000,
        np.nan
    )
    
    # Round up to nearest 5mm for standard pipe sizes
    def round_up_to_5(x):
        return int(np.ceil(x / 5.0) * 5) if not np.isnan(x) else np.nan
    
    # Apply pipe sizing method (ONLY for heat segments)
    if pipe_sizing_method == 'class':
        # Class-based sizing: use maximum diameter for each heat segment type
        max_heat_transmission_main = round_up_to_5(
            export_df.loc[export_df['name'] == 'Heat transmission main', 'diameter_mm'].max()
        )
        max_lq_heat_distribution_main = round_up_to_5(
            export_df.loc[export_df['name'] == 'LQ heat distribution main', 'diameter_mm'].max()
        )
        max_lq_heat_distribution_secondary = round_up_to_5(
            export_df.loc[export_df['name'] == 'LQ heat distribution secondary', 'diameter_mm'].max()
        )
        
        export_df['final_diameter_mm'] = np.select(
            [
                export_df['name'] == 'Heat transmission main',
                export_df['name'] == 'LQ heat distribution main',
                export_df['name'] == 'LQ heat distribution secondary'
            ],
            [
                max_heat_transmission_main,
                max_lq_heat_distribution_main,
                max_lq_heat_distribution_secondary
            ],
            default=np.nan  # Electricity segments get NaN
        )
    
    elif pipe_sizing_method == 'individual':
        # Individual sizing: round each heat pipe diameter individually to nearest 5mm
        # Electricity segments remain NaN
        export_df['final_diameter_mm'] = np.where(
            heat_segments,
            export_df['diameter_mm'].apply(round_up_to_5),
            np.nan
        )
    
    else:
        raise ValueError(f"Invalid pipe_sizing_method '{pipe_sizing_method}'. Must be 'class' or 'individual'")
    
    export_df['name'] = export_df.apply(
        lambda row: f"{row['name']}_DN{int(row['final_diameter_mm'])}" 
                    if pd.notnull(row['final_diameter_mm']) 
                    else row['name'],
        axis=1
    )

    # Filter and sort
    final_export_df = export_df[export_df['capacity_kw'] > 0].sort_values(
        by=['name', 'capacity_kw'],
        ascending=[True, False]
    ).reset_index(drop=True)
    
    # Save to CSV
    os.makedirs(output_folder, exist_ok=True)
    final_export_df.to_csv(os.path.join(output_folder, 'bill_of_materials.csv'), index=False)
    #print(f" Saved bill of materials to {output_folder}/bill_of_materials.csv")
    
    return export_df, total_system_losses_kw, total_LV_losses_kw, supply_losses
