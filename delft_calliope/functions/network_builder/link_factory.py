"""
Link Factory Module

Functions for creating network links:
- Heat transmission links (between heat transmission nodes)
- Electricity transmission links (between electricity transmission nodes)
- Secondary links (demand nodes to transmission nodes)
- Transformer links (transformers to electricity transmission)
- Substation links (warmtenet to substation, substation to heat transmission)
"""

import pandas as pd
import numpy as np
from functions.network_topology import haversine_distance, interpolate_line


def create_transmission_links(stedin_heat_gdf, stedin_elec_gdf, 
                               heat_trans_nodes, elec_trans_nodes,
                               link_parameters, spacing_m):
    """
    Create links between transmission nodes by tracing grid geometries.
    
    Parameters:
    -----------
    stedin_heat_gdf : gpd.GeoDataFrame
        Heat grid network geometry for creating links
    stedin_elec_gdf : gpd.GeoDataFrame
        Electricity grid network geometry for creating links
    heat_trans_nodes : pd.DataFrame
        Heat transmission nodes with 'id', 'lon', 'lat'
    elec_trans_nodes : pd.DataFrame
        Electricity transmission nodes with 'id', 'lon', 'lat'
    link_parameters : dict
        Technical parameters for each link type
    spacing_m : float
        Node spacing in meters for interpolation
    
    Returns:
    --------
    tuple
        (heat_links_df, elec_links_df) DataFrames
    """
    # Build coordinate-to-ID mappings
    coord_to_id_heat = {
        (round(row.lon, 7), round(row.lat, 7)): row.id 
        for _, row in heat_trans_nodes.iterrows()
    }
    coord_to_id_elec = {
        (round(row.lon, 7), round(row.lat, 7)): row.id 
        for _, row in elec_trans_nodes.iterrows()
    }
    
    # Collect heat links
    heat_links = _trace_grid_links(
        stedin_heat_gdf, coord_to_id_heat, link_parameters['LQ heat distribution main'],
        spacing_m, link_type='heat', color='#823740', name='LQ heat distribution main'
    )
    
    # Collect electricity links
    elec_links = _trace_grid_links(
        stedin_elec_gdf, coord_to_id_elec, link_parameters['LV electricity distribution main'],
        spacing_m, link_type='electricity', color='#3186cc', name='LV electricity distribution main'
    )
    
    heat_links_df = pd.DataFrame(heat_links) if heat_links else pd.DataFrame()
    elec_links_df = pd.DataFrame(elec_links) if elec_links else pd.DataFrame()
    
    return heat_links_df, elec_links_df


def _trace_grid_links(grid_gdf, coord_to_id, link_params, spacing_m, 
                       link_type, color, name):
    """
    Trace grid geometry and create links between adjacent nodes.
    
    Parameters:
    -----------
    grid_gdf : gpd.GeoDataFrame
        Grid network geometry
    coord_to_id : dict
        Mapping of (lon, lat) tuples to node IDs
    link_params : dict
        Link parameters with 'flow_cap_max' and 'flow_out_eff_per_distance'
    spacing_m : float
        Node spacing for interpolation
    link_type : str
        'heat' or 'electricity'
    color : str
        Hex color for visualization
    name : str
        Link type name
    
    Returns:
    --------
    list
        List of link dictionaries
    """
    links = []
    suffix = '_heat' if link_type == 'heat' else '_electricity'
    
    for geom in grid_gdf.geometry:
        if geom.geom_type == "LineString":
            coords = list(geom.coords)
            for i in range(len(coords) - 1):
                lat1, lon1 = coords[i][1], coords[i][0]
                lat2, lon2 = coords[i+1][1], coords[i+1][0]
                points = interpolate_line(lat1, lon1, lat2, lon2, spacing_m=spacing_m)
                
                for j in range(len(points) - 1):
                    pt1 = (round(points[j][1], 7), round(points[j][0], 7))
                    pt2 = (round(points[j+1][1], 7), round(points[j+1][0], 7))
                    
                    if pt1 in coord_to_id and pt2 in coord_to_id:
                        node_from = coord_to_id[pt1]
                        node_to = coord_to_id[pt2]
                        
                        if node_from == node_to:
                            continue
                        
                        link_name = f"{node_from}_to_{node_to}{suffix}"
                        links.append({
                            "techs": link_name,
                            "color": color,
                            "name": name,
                            "base_tech": "transmission",
                            "flow_cap_max": link_params['flow_cap_max'],
                            "flow_out_eff_per_distance": link_params['flow_out_eff_per_distance'],
                            "lifetime": 20,
                            "link_to": node_to,
                            "link_from": node_from
                        })
    
    return links


def create_transformer_to_elec_links(transformer_nodes_coordinates, elec_trans_nodes, link_parameters):
    """
    Connect transformers to nearest electricity transmission nodes.
    
    Parameters:
    -----------
    transformer_nodes_coordinates : pd.DataFrame
        Transformer node coordinates
    elec_trans_nodes : pd.DataFrame
        Electricity transmission nodes with 'id', 'lon', 'lat'
    link_parameters : dict
        Link parameters
    
    Returns:
    --------
    pd.DataFrame
        Transformer links DataFrame
    """
    if transformer_nodes_coordinates.empty or elec_trans_nodes.empty:
        return pd.DataFrame()
    
    elec_trans_coords = elec_trans_nodes[['id', 'lon', 'lat']].copy()
    
    mv_lats = transformer_nodes_coordinates['latitude'].values
    mv_lons = transformer_nodes_coordinates['longitude'].values
    elec_lats = elec_trans_coords['lat'].values
    elec_lons = elec_trans_coords['lon'].values
    
    # Vectorized distance calculation
    dists = haversine_distance(
        mv_lats[:, None], mv_lons[:, None], 
        elec_lats[None, :], elec_lons[None, :]
    )
    nearest_idxs = np.argmin(dists, axis=1)
    
    mv_nodes = transformer_nodes_coordinates['nodes'].values
    nearest_elec_ids = elec_trans_coords.iloc[nearest_idxs]['id'].values
    
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
    
    return transformer_links


def create_demand_to_transmission_links(demand_nodes, heat_trans_nodes, elec_trans_nodes, link_parameters):
    """
    Connect demand nodes to nearest heat and electricity transmission nodes.
    
    Parameters:
    -----------
    demand_nodes : pd.DataFrame
        Demand nodes with 'id', 'lon', 'lat'
    heat_trans_nodes : pd.DataFrame
        Heat transmission nodes with 'id', 'lon', 'lat'
    elec_trans_nodes : pd.DataFrame
        Electricity transmission nodes with 'id', 'lon', 'lat'
    link_parameters : dict
        Link parameters
    
    Returns:
    --------
    tuple
        (demand_heat_links, demand_elec_links) DataFrames
    """
    heat_trans_coords = heat_trans_nodes[['id', 'lon', 'lat']].copy()
    elec_trans_coords = elec_trans_nodes[['id', 'lon', 'lat']].copy()
    
    demand_lats = demand_nodes['lat'].values
    demand_lons = demand_nodes['lon'].values
    heat_lats = heat_trans_coords['lat'].values
    heat_lons = heat_trans_coords['lon'].values
    elec_lats = elec_trans_coords['lat'].values
    elec_lons = elec_trans_coords['lon'].values
    
    # Find nearest heat transmission node for each demand node
    dists_heat = haversine_distance(
        demand_lats[:, None], demand_lons[:, None], 
        heat_lats[None, :], heat_lons[None, :]
    )
    nearest_heat_idxs = np.argmin(dists_heat, axis=1)
    
    # Find nearest electricity transmission node for each demand node
    dists_elec = haversine_distance(
        demand_lats[:, None], demand_lons[:, None], 
        elec_lats[None, :], elec_lons[None, :]
    )
    nearest_elec_idxs = np.argmin(dists_elec, axis=1)
    
    demand_ids = demand_nodes['id'].values
    nearest_heat_ids = heat_trans_coords.iloc[nearest_heat_idxs]['id'].values
    nearest_elec_ids = elec_trans_coords.iloc[nearest_elec_idxs]['id'].values
    
    # Create heat links
    link_params = link_parameters['LQ heat distribution secondary']
    demand_heat_links = pd.DataFrame({
        "techs": [f"{d}_to_{h}_heat" for d, h in zip(demand_ids, nearest_heat_ids)],
        "color": "#823740",
        "name": "LQ heat distribution secondary",
        "base_tech": "transmission",
        "flow_cap_max": link_params['flow_cap_max'],
        "flow_out_eff_per_distance": link_params['flow_out_eff_per_distance'],
        "lifetime": 20,
        "link_to": nearest_heat_ids,
        "link_from": demand_ids
    })
    
    # Create electricity links
    link_params = link_parameters['LV electricity distribution secondary']
    demand_elec_links = pd.DataFrame({
        "techs": [f"{d}_to_{e}_electricity" for d, e in zip(demand_ids, nearest_elec_ids)],
        "color": "#3186cc",
        "name": "LV electricity distribution secondary",
        "base_tech": "transmission",
        "flow_cap_max": link_params['flow_cap_max'],
        "flow_out_eff_per_distance": link_params['flow_out_eff_per_distance'],
        "lifetime": 20,
        "link_to": nearest_elec_ids,
        "link_from": demand_ids
    })
    
    return demand_heat_links, demand_elec_links


def create_substation_links(substation_name, sub_lat, sub_lon, 
                            warmtenet_nodes_coordinates, heat_trans_nodes,
                            warmtenet_links_carriers, link_parameters):
    """
    Create links connecting substation to warmtenet and heat transmission network.
    
    Parameters:
    -----------
    substation_name : str
        Name of the substation node
    sub_lat : float
        Latitude of substation
    sub_lon : float
        Longitude of substation
    warmtenet_nodes_coordinates : pd.DataFrame
        Warmtenet node coordinates
    heat_trans_nodes : pd.DataFrame
        Heat transmission nodes
    warmtenet_links_carriers : pd.DataFrame
        Existing warmtenet link carriers
    link_parameters : dict
        Link parameters
    
    Returns:
    --------
    tuple
        (warmtenet_to_substation_link, substation_to_heat_link, updated_warmtenet_carriers)
        Returns (None, None, warmtenet_links_carriers) if no warmtenet nodes found
    """
    # Find warmtenet nodes
    warmtenet_nodes = warmtenet_nodes_coordinates[
        warmtenet_nodes_coordinates['nodes'].str.startswith('warmtenet')
    ]
    
    if warmtenet_nodes.empty:
        return None, None, warmtenet_links_carriers
    
    # Calculate distances to all warmtenet nodes
    warmtenet_lats = warmtenet_nodes['latitude'].values
    warmtenet_lons = warmtenet_nodes['longitude'].values
    dists = haversine_distance(sub_lat, sub_lon, warmtenet_lats, warmtenet_lons)
    nearest_idx = np.argmin(dists)
    nearest_warmtenet_node = warmtenet_nodes.iloc[nearest_idx]['nodes']
    
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
    updated_warmtenet_carriers = pd.concat(
        [warmtenet_links_carriers, warmtenet_link_carrier], ignore_index=True
    )
    
    # Find nearest heat transmission node
    heat_trans_coords = heat_trans_nodes[['id', 'lon', 'lat']].copy()
    heat_lats = heat_trans_coords['lat'].values
    heat_lons = heat_trans_coords['lon'].values
    dists = haversine_distance(sub_lat, sub_lon, heat_lats, heat_lons)
    nearest_heat_idx = np.argmin(dists)
    nearest_heat_id = heat_trans_coords.iloc[nearest_heat_idx]['id']
    
    # Create link from substation to nearest heat transmission node
    link_params = link_parameters['LQ heat distribution main']
    substation_to_heat_link = {
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
    
    return warmtenet_to_substation_link, substation_to_heat_link, updated_warmtenet_carriers


def combine_all_links(warmtenet_links_techs, heat_links_df, elec_links_df,
                      warmtenet_to_substation_link, substation_link,
                      transformer_links, demand_heat_links, demand_elec_links):
    """
    Combine all link types into a single DataFrame.
    
    Returns:
    --------
    pd.DataFrame
        Combined links DataFrame with duplicates removed
    """
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
    
    # Filter out empty DataFrames
    links_list = [df for df in links_list if not df.empty]
    
    links_techs = pd.concat(links_list, ignore_index=True)
    
    # Remove duplicates
    links_techs = links_techs.drop_duplicates(subset=['link_from', 'link_to', 'name'])
    
    return links_techs
