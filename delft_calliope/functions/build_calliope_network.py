import pandas as pd
import numpy as np
import os
import folium
import networkx as nx
from functions.grid_utils import haversine_distance, interpolate_line


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
    
    # ==== BUILD SEPARATE GRAPHS FOR HEAT AND ELECTRICITY NETWORKS ====
    
    # Build HEAT graph (only heat links)
    G_heat = nx.Graph()
    for node in nodes_coordinates['nodes']:
        G_heat.add_node(node)
    
    # Add edges from heat links (techs ending with _heat OR warmtenet/geothermie backbone)
    for _, link in links_techs.iterrows():
        tech_name = link.get('techs', '')
        if pd.notna(tech_name):
            # Include heat distribution links OR warmtenet/geothermie backbone links
            is_heat_link = (tech_name.endswith('_heat') or 
                           tech_name.startswith('geothermie_') or 
                           tech_name.startswith('warmtenet') or
                           tech_name.startswith('substation_'))
            if is_heat_link:
                link_from = link.get('link_from')
                link_to = link.get('link_to')
                if pd.notna(link_from) and pd.notna(link_to):
                    G_heat.add_edge(link_from, link_to)
    
    # Build ELECTRICITY graph (only electricity links)
    G_elec = nx.Graph()
    for node in nodes_coordinates['nodes']:
        G_elec.add_node(node)
    
    # Add edges from electricity links only (techs ending with _electricity)
    for _, link in links_techs.iterrows():
        tech_name = link.get('techs', '')
        if pd.notna(tech_name) and tech_name.endswith('_electricity'):
            link_from = link.get('link_from')
            link_to = link.get('link_to')
            if pd.notna(link_from) and pd.notna(link_to):
                G_elec.add_edge(link_from, link_to)
    
    # ==== CHECK HEAT NETWORK CONNECTIVITY ====
    # Find heat source nodes (geothermie_delft, warmtenet*, substation*)
    heat_source_nodes = {node for node in all_node_names 
                        if node.startswith('geothermie_') or 
                           node.startswith('warmtenet') or 
                           node.startswith('substation_')}
    
    # Find connected components in HEAT network
    heat_components = list(nx.connected_components(G_heat))
    
    # Find component containing heat sources
    heat_component = None
    for component in heat_components:
        if heat_source_nodes & component:  # If component contains any heat source
            heat_component = component
            break
    
    if heat_component is None:
        #print("   WARNING: No heat source found in heat network.")
        heat_isolated_nodes = set()
    else:
        heat_isolated_nodes = demand_node_ids - heat_component
    
    # ==== CHECK ELECTRICITY NETWORK CONNECTIVITY ====
    # Find electricity source nodes (MV_LV_transformer*)
    elec_source_nodes = {node for node in all_node_names 
                        if node.startswith('MV_LV_transformer')}
    
    # Find connected components in ELECTRICITY network
    elec_components = list(nx.connected_components(G_elec))
    
    # Find ALL components containing electricity sources (multiple transformers = multiple islands)
    elec_components_with_source = []
    for component in elec_components:
        if elec_source_nodes & component:  # If component contains any transformer
            elec_components_with_source.append(component)
    
    if not elec_components_with_source:
        #print("   WARNING: No electricity transformers found in electricity network.")
        elec_isolated_nodes = set()
    else:
        # Union of all components with transformers
        elec_connected_nodes = set().union(*elec_components_with_source)
        elec_isolated_nodes = demand_node_ids - elec_connected_nodes
    
    # Combine all isolated nodes
    all_isolated_nodes = heat_isolated_nodes | elec_isolated_nodes
    
    if not all_isolated_nodes:
        return links_techs, set(), []
    
    
    new_links = []
    
    # ==== CREATE HEAT EMERGENCY LINKS ====
    if heat_isolated_nodes and heat_component:
        # Get heat transmission nodes in heat component (LQHtransmission*, warmtenet*, substation*)
        heat_trans_in_component = nodes_coordinates[
            (nodes_coordinates['nodes'].isin(heat_component)) & 
            ((nodes_coordinates['nodes'].str.startswith('LQHtransmission')) |
             (nodes_coordinates['nodes'].str.startswith('warmtenet')) |
             (nodes_coordinates['nodes'].str.startswith('substation_')))
        ]
        
        if not heat_trans_in_component.empty:
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
                distance_km = dists[i, nearest_idx] / 1000.0  # Convert to km
                
                # Create emergency heat connection link
                link_name = f"{demand_id}_to_{nearest_trans_id}_heat"
                link_params = link_parameters['LQ heat distribution secondary']
                
                new_link = {
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
                }
                new_links.append(new_link)
    
    # ==== CREATE ELECTRICITY EMERGENCY LINKS ====
    if elec_isolated_nodes and elec_components_with_source:
        # Get electricity transmission nodes from ALL components with transformers
        elec_trans_in_component = nodes_coordinates[
            (nodes_coordinates['nodes'].isin(elec_connected_nodes)) & 
            ((nodes_coordinates['nodes'].str.startswith('LVEtransmission')) |
             (nodes_coordinates['nodes'].str.startswith('MV_LV_transformer')))
        ]
        
        if not elec_trans_in_component.empty:
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
                distance_km = dists[i, nearest_idx] / 1000.0  # Convert to km
                
                # Create emergency electricity connection link
                link_name = f"{demand_id}_to_{nearest_trans_id}_electricity"
                link_params = link_parameters['LV electricity distribution secondary']
                
                new_link = {
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
                }
                new_links.append(new_link)
    
    # Append new links to links_techs
    if new_links:
        new_links_df = pd.DataFrame(new_links)
        links_techs = pd.concat([links_techs, new_links_df], ignore_index=True)
    
    return links_techs, all_isolated_nodes, new_links


def build_calliope_network(
    merged_df,
    heat_interp_gdf,
    elec_interp_gdf,
    stedin_heat_gdf_delft,
    stedin_elec_gdf_delft,
    stedin_transformers_gdf_delft,
    spacing_m=None,
    mode='plot',
    debug_single_node=False,
    inputs_folder="inputs",
    output_folder="data_tables",
    debug_folder='debug',
    link_parameters=None,
    transformer_supply_capacity=100000,
    neighborhood_id=None,              
    substation_coords=None 
):
    """
    Build the complete network structure by importing base data, creating nodes and links,
    connecting components, and exporting to CSV files.
    
    Parameters:
    -----------
    merged_df : pd.DataFrame
        Demand nodes with building data and heat demand (contains 'id', 'lon', 'lat', 'Peak heat demand (kW)')
    heat_interp_gdf : gpd.GeoDataFrame
        Heat transmission nodes with geometry (contains 'lon', 'lat')
    elec_interp_gdf : gpd.GeoDataFrame
        Electricity transmission nodes with geometry (contains 'lon', 'lat')
    stedin_heat_gdf_delft : gpd.GeoDataFrame
        Heat grid network geometry for creating links
    stedin_elec_gdf_delft : gpd.GeoDataFrame
        Electricity grid network geometry for creating links
    stedin_transformers_gdf_delft : gpd.GeoDataFrame
        MV-LV transformer locations with Polygon geometries in EPSG:4326
    spacing_m : float
        Node spacing in meters for interpolation
    mode : str, optional
        Run mode: 'plot' to generate visualization, 'export' to skip visualization (default: 'plot')
    debug_single_node : bool, optional
        If True, only keep one demand node for quick debugging (default: False)
    inputs_folder : str, optional
        Folder containing input CSV files (default: "inputs")
    output_folder : str, optional
        Folder to save output CSV files (default: "data_tables")
    link_parameters : dict, optional
        Technical parameters for each link type (default: all 10000 kW, efficiency 1.0)
            Keys: 'Heat transmission main', 'LQ heat distribution main', 
                'LQ heat distribution secondary', 'LV electricity distribution main',
                'LV electricity distribution secondary'
            Values: dict with 'flow_cap_max' and 'flow_out_eff_per_distance'
    transformer_supply_capacity : int, optional
        Maximum electricity supply capacity per transformer in kW (default: 100000)
    neighborhood_id : str, optional
        Neighborhood identifier for substation naming (e.g., 'multatulibuurt')
        If None, uses generic 'main' name
    substation_coords : list, optional
        [lon, lat] coordinates for the substation location
        If None, substation will not be created
    
    Returns:
    --------
    dict
        Dictionary containing all network DataFrames:
        - 'warmtenet_links_carriers': Base warmtenet link carriers
        - 'nodes_techs': All node technology assignments
        - 'nodes_coordinates': All node coordinates
        - 'links_techs': All link technical specifications
        - 'links_LQ_heat': LQ heat link carriers
        - 'links_electricity': Electricity link carriers
        - 'links_costs': Link cost parameters
    
    Side Effects:
    -------------
    - Saves 7 CSV files to output_folder/
    - If mode=='plot', saves network visualization to debug/network_map.html
    """
    
    # Default link parameters if not provided
    if link_parameters is None:
        link_parameters = {
            'Heat transmission main': {'flow_cap_max': 100000, 'flow_out_eff_per_distance': 1},
            'LQ heat distribution main': {'flow_cap_max': 100000, 'flow_out_eff_per_distance': 1},
            'LQ heat distribution secondary': {'flow_cap_max': 100000, 'flow_out_eff_per_distance': 1},
            'LV electricity distribution main': {'flow_cap_max': 100000, 'flow_out_eff_per_distance': 1},
            'LV electricity distribution secondary': {'flow_cap_max': 100000, 'flow_out_eff_per_distance': 1}
        }

     # --- 1. Import CSV files from inputs folder ---
    #print(f"Importing CSV files from {inputs_folder}...")
    
    # Read required CSV files (warmtenet only, transformers are generated from geodata)
    warmtenet_links_carriers = pd.read_csv(os.path.join(inputs_folder, "warmtenet_links_carriers.csv"))
    warmtenet_nodes_techs = pd.read_csv(os.path.join(inputs_folder, "warmtenet_nodes_techs.csv"))
    warmtenet_nodes_coordinates = pd.read_csv(os.path.join(inputs_folder, "warmtenet_nodes_coordinates.csv"))
    warmtenet_links_techs = pd.read_csv(os.path.join(inputs_folder, "warmtenet_links_techs.csv"))
    
    # Generate transformer nodes from GeoDataFrame
    if not stedin_transformers_gdf_delft.empty:
        # Convert to projected CRS for accurate centroid calculation
        transformers_projected = stedin_transformers_gdf_delft.to_crs(epsg=28992)
        centroids_projected = transformers_projected.geometry.centroid
        
        # Convert centroids back to WGS84
        centroids_wgs84 = centroids_projected.to_crs(epsg=4326)
        
        # Create transformer node names (1-based indexing for consistency)
        transformer_node_names = [f"MV_LV_transformer{i+1}" for i in range(len(stedin_transformers_gdf_delft))]
        
        # Create transformer nodes coordinates DataFrame
        MV_LV_transformer_nodes_coordinates = pd.DataFrame({
            'nodes': transformer_node_names,
            'latitude': centroids_wgs84.y.values,
            'longitude': centroids_wgs84.x.values,
            'comment': ''
        })
        
        # Create transformer nodes techs DataFrame
        MV_LV_transformer_nodes_techs = pd.DataFrame({
            'nodes': transformer_node_names,
            'techs': 'supply_LV_electricity',
            'parameters': 'source_use_max',
            'timesteps': '',
            '2050/01/01 00:00': transformer_supply_capacity
        })
        
        #print(f" Generated {len(MV_LV_transformer_nodes_techs)} transformer nodes from geodata")
    else:
        # If no transformers found, create empty DataFrames
        MV_LV_transformer_nodes_coordinates = pd.DataFrame(columns=['nodes', 'latitude', 'longitude', 'comment'])
        MV_LV_transformer_nodes_techs = pd.DataFrame(columns=['nodes', 'techs', 'parameters', 'timesteps', '2050/01/01 00:00'])
        #print(" No transformers found in geodata")
    
    #print(f" Loaded {len(warmtenet_nodes_techs)} warmtenet node techs, {len(MV_LV_transformer_nodes_techs)} transformer node techs")    
    # --- 2. Add demand and transmission nodes ---
    #print("Creating demand and transmission nodes...")
    
    # Create demand nodes
    demand_nodes = merged_df.copy()
    # Remove any non-numeric prefix, keep only numbers, then add 'D' prefix
    demand_nodes['id'] = 'D' + demand_nodes['id'].astype(str).str.extract(r'(\d+)', expand=False)
    
    # Debug mode: keep only one demand node
    if debug_single_node:
        print(" DEBUG MODE: Keeping only 1 demand node for testing")
        demand_nodes = demand_nodes.iloc[[0]].copy()
    
    # Create heat transmission nodes
    heat_trans_nodes = heat_interp_gdf.copy()
    heat_trans_nodes["id"] = [f"LQHtransmission{i+1}" for i in range(len(heat_trans_nodes))]
    
    # Create electricity transmission nodes
    elec_trans_nodes = elec_interp_gdf.copy()
    elec_trans_nodes["id"] = [f"LVEtransmission{i+1}" for i in range(len(elec_trans_nodes))]
    
    # Create demand node techs
    demand_techs = pd.DataFrame({
        "nodes": demand_nodes["id"],
        "techs": "demand_LQ_heat",
        "parameters": "sink_use_equals",
        "timesteps": "",
        "2050/01/01 00:00": demand_nodes["Peak heat demand (kW)"]
    })
    
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
    
    # Combine all node techs
    transmission_techs = pd.concat([heat_trans_techs, elec_trans_techs], ignore_index=True)
    new_techs = pd.concat([demand_techs, transmission_techs], ignore_index=True)
    old_techs = pd.concat([warmtenet_nodes_techs, MV_LV_transformer_nodes_techs], ignore_index=True)
    nodes_techs = pd.concat([old_techs, new_techs], ignore_index=True)
    
    # Create node coordinates
    demand_coords = demand_nodes[["id", "lon", "lat"]].copy().rename(columns={"id": "nodes", "lon": "longitude", "lat": "latitude"})
    heat_trans_coords = heat_trans_nodes[["id", "lon", "lat"]].copy().rename(columns={"id": "nodes", "lon": "longitude", "lat": "latitude"})
    elec_trans_coords = elec_trans_nodes[["id", "lon", "lat"]].copy().rename(columns={"id": "nodes", "lon": "longitude", "lat": "latitude"})
    
    trans_coords = pd.concat([heat_trans_coords, elec_trans_coords], ignore_index=True)
    new_coords = pd.concat([demand_coords, trans_coords], ignore_index=True)
    old_coords = pd.concat([warmtenet_nodes_coordinates, MV_LV_transformer_nodes_coordinates], ignore_index=True)
    nodes_coordinates = pd.concat([old_coords, new_coords], ignore_index=True)
    
    #print(f" Created {len(demand_nodes)} demand nodes, {len(heat_trans_nodes)} heat transmission nodes, {len(elec_trans_nodes)} elec transmission nodes")
    
    # --- 3. Add links between transmission nodes ---
    #print("Creating links between transmission nodes...")
    
    # Build coordinate-to-ID mappings
    coord_to_id_heat = {(round(row.lon, 7), round(row.lat, 7)): row.id for _, row in heat_trans_nodes.iterrows()}
    coord_to_id_elec = {(round(row.lon, 7), round(row.lat, 7)): row.id for _, row in elec_trans_nodes.iterrows()}
    
    # Collect heat links
    heat_links = []
    link_params = link_parameters['LQ heat distribution main']
    for geom in stedin_heat_gdf_delft.geometry:
        if geom.geom_type == "LineString":
            coords = list(geom.coords)
            for i in range(len(coords) - 1):
                lat1, lon1 = coords[i][1], coords[i][0]
                lat2, lon2 = coords[i+1][1], coords[i+1][0]
                points = interpolate_line(lat1, lon1, lat2, lon2, spacing_m=spacing_m)
                for j in range(len(points) - 1):
                    pt1 = (round(points[j][1], 7), round(points[j][0], 7))
                    pt2 = (round(points[j+1][1], 7), round(points[j+1][0], 7))
                    if pt1 in coord_to_id_heat and pt2 in coord_to_id_heat:
                        node_from = coord_to_id_heat[pt1]
                        node_to = coord_to_id_heat[pt2]

                        if node_from == node_to:
                            continue

                        link_name_heat = f"{node_from}_to_{node_to}_heat"
                        heat_links.append({
                            "techs": link_name_heat,
                            "color": "#823740",
                            "name": "LQ heat distribution main",
                            "base_tech": "transmission",
                            "flow_cap_max": link_params['flow_cap_max'],
                            "flow_out_eff_per_distance": link_params['flow_out_eff_per_distance'],
                            "lifetime": 20,
                            "link_to": node_to,
                            "link_from": node_from
                        })
    
    # Collect electricity links
    elec_links = []
    link_params = link_parameters['LV electricity distribution main']
    for geom in stedin_elec_gdf_delft.geometry:
        if geom.geom_type == "LineString":
            coords = list(geom.coords)
            for i in range(len(coords) - 1):
                lat1, lon1 = coords[i][1], coords[i][0]
                lat2, lon2 = coords[i+1][1], coords[i+1][0]
                points = interpolate_line(lat1, lon1, lat2, lon2, spacing_m=spacing_m)
                for j in range(len(points) - 1):
                    pt1 = (round(points[j][1], 7), round(points[j][0], 7))
                    pt2 = (round(points[j+1][1], 7), round(points[j+1][0], 7))
                    if pt1 in coord_to_id_elec and pt2 in coord_to_id_elec:
                        node_from = coord_to_id_elec[pt1]
                        node_to = coord_to_id_elec[pt2]

                        if node_from == node_to:
                            continue

                        link_name_elec = f"{node_from}_to_{node_to}_electricity"
                        elec_links.append({
                            "techs": link_name_elec,
                            "color": "#3186cc",
                            "name": "LV electricity distribution main",
                            "base_tech": "transmission",
                            "flow_cap_max": link_params['flow_cap_max'],
                            "flow_out_eff_per_distance": link_params['flow_out_eff_per_distance'],
                            "lifetime": 20,
                            "link_to": node_to,
                            "link_from": node_from
                        })
    
    #print(f" Created {len(heat_links)} heat links, {len(elec_links)} electricity links between transmission nodes")
    
    # --- 4. Connect demand nodes, substations, and transformers to distribution network ---
    #print("Connecting nodes to distribution network...")
    
    # Create substation dynamically if coordinates provided
    substation_link = None
    warmtenet_to_substation_link = None
    
    if substation_coords is not None:
        # Generate substation name based on neighborhood
        substation_name = f"substation_{neighborhood_id}" if neighborhood_id else "substation_main"
        sub_lon, sub_lat = substation_coords[0], substation_coords[1]
        
        # Find nearest warmtenet node to connect substation to
        warmtenet_nodes = warmtenet_nodes_coordinates[
            warmtenet_nodes_coordinates['nodes'].str.startswith('warmtenet')
        ]
        
        if not warmtenet_nodes.empty:
            # Calculate distances to all warmtenet nodes
            warmtenet_lats = warmtenet_nodes['latitude'].values
            warmtenet_lons = warmtenet_nodes['longitude'].values
            dists = haversine_distance(sub_lat, sub_lon, warmtenet_lats, warmtenet_lons)
            nearest_idx = np.argmin(dists)
            nearest_warmtenet_node = warmtenet_nodes.iloc[nearest_idx]['nodes']
            
            #print(f"   Connecting substation '{substation_name}' to warmtenet node '{nearest_warmtenet_node}'")
            
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
            
            # Create link from warmtenet to substation (HQ heat transmission)
            warmtenet_to_substation_link = {
                "techs": f"{nearest_warmtenet_node}_to_{substation_name}",
                "color": "#823747",
                "name": "Heat transmission main",
                "base_tech": "transmission",
                "flow_cap_max": link_parameters['Heat transmission main']['flow_cap_max'],
                "flow_out_eff_per_distance": link_parameters['Heat transmission main']['flow_out_eff_per_distance'],
                "lifetime": 20,
                "link_to": nearest_warmtenet_node,
                "link_from": substation_name
            }
            
            # Add to warmtenet_links_carriers
            warmtenet_link_carrier = pd.DataFrame({
                'techs': [f"{nearest_warmtenet_node}_to_{substation_name}"],
                'carrier_out': [1],
                'carrier_in': [1]
            })
            warmtenet_links_carriers = pd.concat([warmtenet_links_carriers, warmtenet_link_carrier], ignore_index=True)
            
            # Create link from substation to nearest heat transmission node (LQ heat distribution)
            # Get transmission node coordinates
            heat_trans_nodes_coords = heat_trans_nodes[['id', 'lon', 'lat']].copy()
            heat_lats = heat_trans_nodes_coords['lat'].values
            heat_lons = heat_trans_nodes_coords['lon'].values
            dists = haversine_distance(sub_lat, sub_lon, heat_lats, heat_lons)
            nearest_heat_idx = np.argmin(dists)
            nearest_heat_id = heat_trans_nodes_coords.iloc[nearest_heat_idx]['id']
            
            link_params = link_parameters['LQ heat distribution main']
            substation_link = {
                "techs": f"{substation_name}_to_{nearest_heat_id}_heat",
                "color": "#823740",
                "name": "LQ heat distribution main",
                "base_tech": "transmission",
                "flow_cap_max": link_params['flow_cap_max'],
                "flow_out_eff_per_distance": link_params['flow_out_eff_per_distance'],
                "lifetime": 20,
                "link_to": nearest_heat_id,
                "link_from": substation_name
            }
            
            #print(f"   Created substation '{substation_name}' and links")
        else:
            print("   WARNING: No warmtenet nodes found, skipping substation creation")
    
    # Get transmission node coordinates for transformer connections
    elec_trans_nodes_coords = elec_trans_nodes[['id', 'lon', 'lat']].copy()
    
    # Get transmission node coordinates for transformer connections
    elec_trans_nodes_coords = elec_trans_nodes[['id', 'lon', 'lat']].copy()
    
    # Transformers to nearest electricity node (vectorized)
    mv_lats = MV_LV_transformer_nodes_coordinates['latitude'].values
    mv_lons = MV_LV_transformer_nodes_coordinates['longitude'].values
    elec_lats = elec_trans_nodes_coords['lat'].values
    elec_lons = elec_trans_nodes_coords['lon'].values
    
    dists = haversine_distance(mv_lats[:, None], mv_lons[:, None], elec_lats[None, :], elec_lons[None, :])
    nearest_idxs = np.argmin(dists, axis=1)
    
    mv_nodes = MV_LV_transformer_nodes_coordinates['nodes'].values
    nearest_elec_ids = elec_trans_nodes_coords.iloc[nearest_idxs]['id'].values
    
    link_params = link_parameters['LV electricity distribution main']
    transformer_links = pd.DataFrame({
        "techs": [f"{mv}_to_{elec}_electricity" for mv, elec in zip(mv_nodes, nearest_elec_ids)],
        "color": "#3186cc",
        "name": "LV electricity distribution main",
        "base_tech": "transmission",
        "flow_cap_max": link_params['flow_cap_max'],
        "flow_out_eff_per_distance": link_params['flow_out_eff_per_distance'],
        "lifetime": 20,
        "link_to": nearest_elec_ids,
        "link_from": mv_nodes
    })
    
    # Demand nodes to nearest heat and electricity nodes (vectorized)
    demand_lats = demand_nodes['lat'].values
    demand_lons = demand_nodes['lon'].values
    
    dists_heat = haversine_distance(demand_lats[:, None], demand_lons[:, None], heat_lats[None, :], heat_lons[None, :])
    nearest_heat_idxs = np.argmin(dists_heat, axis=1)
    
    dists_elec = haversine_distance(demand_lats[:, None], demand_lons[:, None], elec_lats[None, :], elec_lons[None, :])
    nearest_elec_idxs = np.argmin(dists_elec, axis=1)
    
    demand_ids = demand_nodes['id'].values
    nearest_heat_ids_demand = heat_trans_nodes_coords.iloc[nearest_heat_idxs]['id'].values
    nearest_elec_ids_demand = elec_trans_nodes_coords.iloc[nearest_elec_idxs]['id'].values
    
    link_params = link_parameters['LQ heat distribution secondary']
    demand_heat_links = pd.DataFrame({
        "techs": [f"{d}_to_{h}_heat" for d, h in zip(demand_ids, nearest_heat_ids_demand)],
        "color": "#823740",
        "name": "LQ heat distribution secondary",
        "base_tech": "transmission",
        "flow_cap_max": link_params['flow_cap_max'],
        "flow_out_eff_per_distance": link_params['flow_out_eff_per_distance'],
        "lifetime": 20,
        "link_to": nearest_heat_ids_demand,
        "link_from": demand_ids
    })
    
    link_params = link_parameters['LV electricity distribution secondary']
    demand_elec_links = pd.DataFrame({
        "techs": [f"{d}_to_{e}_electricity" for d, e in zip(demand_ids, nearest_elec_ids_demand)],
        "color": "#3186cc",
        "name": "LV electricity distribution secondary",
        "base_tech": "transmission",
        "flow_cap_max": link_params['flow_cap_max'],
        "flow_out_eff_per_distance": link_params['flow_out_eff_per_distance'],
        "lifetime": 20,
        "link_to": nearest_elec_ids_demand,
        "link_from": demand_ids
    })
    
    #print(f" Created connections: 1 substation link, {len(transformer_links)} transformer links, {len(demand_heat_links)} demand heat links, {len(demand_elec_links)} demand elec links")
    
    # Combine all links
    heat_links_df = pd.DataFrame(heat_links) if heat_links else pd.DataFrame()
    elec_links_df = pd.DataFrame(elec_links) if elec_links else pd.DataFrame()
    
    links_list = [
        warmtenet_links_techs,
        heat_links_df,
        elec_links_df
    ]
    
    # Add substation links if they were created
    if warmtenet_to_substation_link is not None:
        links_list.append(pd.DataFrame([warmtenet_to_substation_link]))
    if substation_link is not None:
        links_list.append(pd.DataFrame([substation_link]))
    
    links_list.extend([
        transformer_links,
        demand_heat_links,
        demand_elec_links
    ])
    
    links_techs = pd.concat(links_list, ignore_index=True)
    
    # Remove duplicates
    links_techs = links_techs.drop_duplicates(subset=['link_from', 'link_to', 'name'])
    
    #print(f" Total links: {len(links_techs)}")
    
    # --- 5. Create link carrier and cost DataFrames ---
    #print("Creating link carrier and cost DataFrames...")
    
    # Create links_LQ_heat
    links_LQ_heat = warmtenet_links_carriers.iloc[0:0].copy()
    lq_heat_techs = links_techs.loc[links_techs['name'].str.contains("LQ heat distribution", na=False), 'techs']
    
    new_rows = pd.DataFrame(1, index=range(len(lq_heat_techs)), columns=links_LQ_heat.columns)
    new_rows['techs'] = lq_heat_techs.values
    links_LQ_heat = pd.concat([links_LQ_heat, new_rows], ignore_index=True)
    
    # Create links_electricity
    lv_elec_techs = links_techs.loc[links_techs['name'].str.contains("LV electricity distribution", na=False), 'techs']
    
    new_rows_elec = pd.DataFrame(1, index=range(len(lv_elec_techs)), columns=warmtenet_links_carriers.columns)
    new_rows_elec['techs'] = lv_elec_techs.values
    links_electricity = pd.concat([warmtenet_links_carriers.iloc[0:0].copy(), new_rows_elec], ignore_index=True)
    
    # Create links_costs
    links_costs = pd.DataFrame({
        'techs': links_techs['techs'],
        'cost_flow_cap_per_distance': 100
    })
    
    #print(f" Created {len(links_LQ_heat)} LQ heat carriers, {len(links_electricity)} electricity carriers, {len(links_costs)} cost entries")
    
    # --- 6. Ensure demand node connectivity ---
    #print("Checking network connectivity...")
    links_techs, isolated_demand_nodes, emergency_links = ensure_demand_connectivity(
        nodes_coordinates, links_techs, link_parameters, demand_nodes, 
        heat_trans_nodes, haversine_distance
    )
    
    if isolated_demand_nodes:
        #print(f" WARNING: Found {len(isolated_demand_nodes)} isolated demand nodes.")
        #print(f"   Isolated nodes: {isolated_demand_nodes}")
        #print(f"   Created {len(emergency_links)} emergency connections to network components.")
        
        # Separate heat and electricity emergency links
        heat_emergency_links = [link for link in emergency_links if link['techs'].endswith('_heat')]
        elec_emergency_links = [link for link in emergency_links if link['techs'].endswith('_electricity')]
        
        # Add heat emergency links to links_LQ_heat carriers
        if heat_emergency_links:
            emergency_lq_heat = pd.DataFrame({
                'techs': [link['techs'] for link in heat_emergency_links],
                'carrier_out': [1] * len(heat_emergency_links),
                'carrier_in': [1] * len(heat_emergency_links)
            })
            links_LQ_heat = pd.concat([links_LQ_heat, emergency_lq_heat], ignore_index=True)
            
            # Add heat emergency links to links_costs
            heat_emergency_costs = pd.DataFrame({
                'techs': [link['techs'] for link in heat_emergency_links],
                'cost_flow_cap_per_distance': [100] * len(heat_emergency_links)
            })
            links_costs = pd.concat([links_costs, heat_emergency_costs], ignore_index=True)
        
        # Add electricity emergency links to links_electricity carriers
        if elec_emergency_links:
            emergency_electricity = pd.DataFrame({
                'techs': [link['techs'] for link in elec_emergency_links],
                'carrier_out': [1] * len(elec_emergency_links),
                'carrier_in': [1] * len(elec_emergency_links)
            })
            links_electricity = pd.concat([links_electricity, emergency_electricity], ignore_index=True)
            
            # Add electricity emergency links to links_costs
            elec_emergency_costs = pd.DataFrame({
                'techs': [link['techs'] for link in elec_emergency_links],
                'cost_flow_cap_per_distance': [100] * len(elec_emergency_links)
            })
            links_costs = pd.concat([links_costs, elec_emergency_costs], ignore_index=True)
    
    # --- 7. Save DataFrames to CSV files ---
    #print(f"Saving DataFrames to {output_folder}...")
    
    os.makedirs(output_folder, exist_ok=True)
    
    warmtenet_links_carriers.to_csv(os.path.join(output_folder, 'warmtenet_links_carriers.csv'), index=False)
    nodes_techs.to_csv(os.path.join(output_folder, 'nodes_techs.csv'), index=False)
    nodes_coordinates.to_csv(os.path.join(output_folder, 'nodes_coordinates.csv'), index=False)
    links_techs.to_csv(os.path.join(output_folder, 'links_techs.csv'), index=False)
    links_LQ_heat.to_csv(os.path.join(output_folder, 'links_LQ_heat.csv'), index=False)
    links_electricity.to_csv(os.path.join(output_folder, 'links_electricity.csv'), index=False)
    links_costs.to_csv(os.path.join(output_folder, 'links_costs.csv'), index=False)
    
    #print(f" Saved 7 CSV files to {output_folder}/")
    
    # --- 8. Visualize network (if mode=='plot') ---
    if mode == 'plot':
        #print("Generating network visualization...")
        
        def is_valid_coord(val):
            try:
                float(val)
                return True
            except (TypeError, ValueError):
                return False
        
        # Prepare node coordinates DataFrame
        node_coords = nodes_coordinates.set_index('nodes')
        
        # Prepare links DataFrame - extract link_from and link_to if not present
        links_techs_viz = links_techs.copy()
        if 'link_from' not in links_techs_viz.columns or 'link_to' not in links_techs_viz.columns:
            links_techs_viz[['link_from', 'link_to']] = links_techs_viz['techs'].str.extract(r'^(.*?)_to_(.*?)_')
        
        # Create Folium map centered on mean coordinates
        center_lat = node_coords['latitude'].mean()
        center_lon = node_coords['longitude'].mean()
        network_map = folium.Map(location=[center_lat, center_lon], zoom_start=15, tiles='OpenStreetMap')
        
        # Create FeatureGroups for heat and electricity links
        heat_links_group = folium.FeatureGroup(name="Heat Links", show=True)
        elec_links_group = folium.FeatureGroup(name="Electricity Links", show=True)
        
        # Add nodes as circle markers
        for node, row in node_coords.iterrows():
            folium.CircleMarker(
                location=[row['latitude'], row['longitude']],
                radius=4,
                color='red',
                fill=True,
                fill_color='red',
                fill_opacity=0.7,
                popup=f"Node: {node}"
            ).add_to(network_map)
        
        # Add links as lines, separated by type
        for _, link in links_techs_viz.iterrows():
            from_node = link['link_from']
            to_node = link['link_to']
            if from_node in node_coords.index and to_node in node_coords.index:
                from_lat, from_lon = node_coords.loc[from_node, ['latitude', 'longitude']]
                to_lat, to_lon = node_coords.loc[to_node, ['latitude', 'longitude']]
                if all(is_valid_coord(x) for x in [from_lat, from_lon, to_lat, to_lon]):
                    if "LQ heat distribution" in link['name']:
                        folium.PolyLine(
                            locations=[[from_lat, from_lon], [to_lat, to_lon]],
                            color='#ff5100',
                            weight=2,
                            opacity=0.7,
                            popup=f"{from_node}  {to_node}"
                        ).add_to(heat_links_group)
                    elif "LV electricity distribution" in link['name']:
                        folium.PolyLine(
                            locations=[[from_lat, from_lon], [to_lat, to_lon]],
                            color='#3186cc',
                            weight=2,
                            opacity=0.7,
                            popup=f"{from_node}  {to_node}"
                        ).add_to(elec_links_group)
        
        # Add groups to map and layer control
        heat_links_group.add_to(network_map)
        elec_links_group.add_to(network_map)
        folium.LayerControl().add_to(network_map)
        
        # Save the map
        os.makedirs(debug_folder, exist_ok=True)
        network_map.save(os.path.join(debug_folder, 'calliope_map.html'))
        #print(f" Saved network visualization to debug/network_map.html")
    
    # Return all DataFrames
    return {
        'warmtenet_links_carriers': warmtenet_links_carriers,
        'nodes_techs': nodes_techs,
        'nodes_coordinates': nodes_coordinates,
        'links_techs': links_techs,
        'links_LQ_heat': links_LQ_heat,
        'links_electricity': links_electricity,
        'links_costs': links_costs,
        'connectivity_info': {
            'num_isolated_demand_nodes': len(isolated_demand_nodes),
            'isolated_demand_nodes': list(isolated_demand_nodes),
            'total_demand_nodes': len(demand_nodes)
        }
    }
