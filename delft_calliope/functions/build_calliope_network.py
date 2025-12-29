import pandas as pd
import numpy as np
import os
import folium
from functions.grid_utils import haversine_distance, interpolate_line

def build_calliope_network(
    merged_df,
    heat_interp_gdf,
    elec_interp_gdf,
    stedin_heat_gdf_delft,
    stedin_elec_gdf_delft,
    spacing_m=None,
    mode='plot',
    debug_single_node=False,
    inputs_folder="inputs",
    output_folder="data_tables"
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
    
    # --- 1. Import CSV files from inputs folder ---
    #print(f"Importing CSV files from {inputs_folder}...")
    
    # Read required CSV files
    warmtenet_links_carriers = pd.read_csv(os.path.join(inputs_folder, "warmtenet_links_carriers.csv"))
    warmtenet_nodes_techs = pd.read_csv(os.path.join(inputs_folder, "warmtenet_nodes_techs.csv"))
    warmtenet_nodes_coordinates = pd.read_csv(os.path.join(inputs_folder, "warmtenet_nodes_coordinates.csv"))
    warmtenet_links_techs = pd.read_csv(os.path.join(inputs_folder, "warmtenet_links_techs.csv"))
    MV_LV_transformer_nodes_techs = pd.read_csv(os.path.join(inputs_folder, "MV_LV_transformer_nodes_techs.csv"))
    MV_LV_transformer_nodes_coordinates = pd.read_csv(os.path.join(inputs_folder, "MV_LV_transformer_nodes_coordinates.csv"))
    
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
                        link_name_heat = f"{node_from}_to_{node_to}_heat"
                        heat_links.append({
                            "techs": link_name_heat,
                            "color": "#823740",
                            "name": "LQ heat distribution main",
                            "base_tech": "transmission",
                            "flow_cap_max": 10000,
                            "flow_out_eff_per_distance": 1,
                            "lifetime": 20,
                            "link_to": node_to,
                            "link_from": node_from
                        })
    
    # Collect electricity links
    elec_links = []
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
                        link_name_elec = f"{node_from}_to_{node_to}_electricity"
                        elec_links.append({
                            "techs": link_name_elec,
                            "color": "#3186cc",
                            "name": "LV electricity distribution main",
                            "base_tech": "transmission",
                            "flow_cap_max": 10000,
                            "flow_out_eff_per_distance": 1,
                            "lifetime": 20,
                            "link_to": node_to,
                            "link_from": node_from
                        })
    
    #print(f" Created {len(heat_links)} heat links, {len(elec_links)} electricity links between transmission nodes")
    
    # --- 4. Connect demand nodes, substations, and transformers to distribution network ---
    #print("Connecting nodes to distribution network...")
    
    # Get substation coordinates
    substation_row = warmtenet_nodes_coordinates[warmtenet_nodes_coordinates['nodes'] == 'substation_multatulibuurt']
    if substation_row.empty:
        raise ValueError("substation_multatulibuurt not found in warmtenet_nodes_coordinates")
    sub_lon = substation_row.iloc[0]['longitude']
    sub_lat = substation_row.iloc[0]['latitude']
    
    # Get transmission node coordinates
    heat_trans_nodes_coords = heat_trans_nodes[['id', 'lon', 'lat']].copy()
    elec_trans_nodes_coords = elec_trans_nodes[['id', 'lon', 'lat']].copy()
    
    # Substation to nearest heat node (vectorized)
    heat_lats = heat_trans_nodes_coords['lat'].values
    heat_lons = heat_trans_nodes_coords['lon'].values
    dists = haversine_distance(sub_lat, sub_lon, heat_lats, heat_lons)
    nearest_heat_idx = np.argmin(dists)
    nearest_heat_id = heat_trans_nodes_coords.iloc[nearest_heat_idx]['id']
    
    substation_link = {
        "techs": f"substation_multatulibuurt_to_{nearest_heat_id}_heat",
        "color": "#823740",
        "name": "LQ heat distribution main",
        "base_tech": "transmission",
        "flow_cap_max": 10000,
        "flow_out_eff_per_distance": 1,
        "lifetime": 20,
        "link_to": nearest_heat_id,
        "link_from": "substation_multatulibuurt"
    }
    
    # Transformers to nearest electricity node (vectorized)
    mv_lats = MV_LV_transformer_nodes_coordinates['latitude'].values
    mv_lons = MV_LV_transformer_nodes_coordinates['longitude'].values
    elec_lats = elec_trans_nodes_coords['lat'].values
    elec_lons = elec_trans_nodes_coords['lon'].values
    
    dists = haversine_distance(mv_lats[:, None], mv_lons[:, None], elec_lats[None, :], elec_lons[None, :])
    nearest_idxs = np.argmin(dists, axis=1)
    
    mv_nodes = MV_LV_transformer_nodes_coordinates['nodes'].values
    nearest_elec_ids = elec_trans_nodes_coords.iloc[nearest_idxs]['id'].values
    
    transformer_links = pd.DataFrame({
        "techs": [f"{mv}_to_{elec}_electricity" for mv, elec in zip(mv_nodes, nearest_elec_ids)],
        "color": "#3186cc",
        "name": "LV electricity distribution main",
        "base_tech": "transmission",
        "flow_cap_max": 10000,
        "flow_out_eff_per_distance": 1,
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
    
    demand_heat_links = pd.DataFrame({
        "techs": [f"{d}_to_{h}_heat" for d, h in zip(demand_ids, nearest_heat_ids_demand)],
        "color": "#823740",
        "name": "LQ heat distribution secondary",
        "base_tech": "transmission",
        "flow_cap_max": 10000,
        "flow_out_eff_per_distance": 1,
        "lifetime": 20,
        "link_to": nearest_heat_ids_demand,
        "link_from": demand_ids
    })
    
    demand_elec_links = pd.DataFrame({
        "techs": [f"{d}_to_{e}_electricity" for d, e in zip(demand_ids, nearest_elec_ids_demand)],
        "color": "#3186cc",
        "name": "LV electricity distribution secondary",
        "base_tech": "transmission",
        "flow_cap_max": 10000,
        "flow_out_eff_per_distance": 1,
        "lifetime": 20,
        "link_to": nearest_elec_ids_demand,
        "link_from": demand_ids
    })
    
    #print(f" Created connections: 1 substation link, {len(transformer_links)} transformer links, {len(demand_heat_links)} demand heat links, {len(demand_elec_links)} demand elec links")
    
    # Combine all links
    new_transmission_links = pd.concat([pd.DataFrame(heat_links), pd.DataFrame(elec_links)], ignore_index=True)
    links_techs = pd.concat([
        warmtenet_links_techs,
        new_transmission_links,
        pd.DataFrame([substation_link]),
        transformer_links,
        demand_heat_links,
        demand_elec_links
    ], ignore_index=True)
    
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
    
    # --- 6. Save DataFrames to CSV files ---
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
    
    # --- 7. Visualize network (if mode=='plot') ---
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
        os.makedirs('debug', exist_ok=True)
        network_map.save('debug/network_map.html')
        #print(f" Saved network visualization to debug/network_map.html")
    
    # Return all DataFrames
    return {
        'warmtenet_links_carriers': warmtenet_links_carriers,
        'nodes_techs': nodes_techs,
        'nodes_coordinates': nodes_coordinates,
        'links_techs': links_techs,
        'links_LQ_heat': links_LQ_heat,
        'links_electricity': links_electricity,
        'links_costs': links_costs
    }
