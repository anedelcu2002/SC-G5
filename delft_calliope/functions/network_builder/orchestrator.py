"""
Network Builder Orchestrator

Main entry point for building Calliope energy network structures.
Coordinates all submodules to create a complete network.
"""

import os
import pandas as pd

from functions.network_topology import haversine_distance
from functions.network_builder.node_factory import (
    create_transformer_nodes,
    create_demand_nodes,
    create_transmission_nodes_df,
    combine_all_nodes,
    add_substation_node
)
from functions.network_builder.link_factory import (
    create_transmission_links,
    create_transformer_to_elec_links,
    create_demand_to_transmission_links,
    create_substation_links,
    combine_all_links
)
from functions.network_builder.connectivity import ensure_demand_connectivity
from functions.network_builder.carrier_cost_builder import (
    create_link_carriers,
    create_link_costs,
    add_emergency_links_to_carriers
)
from functions.network_builder.exporter import export_network_csvs
from functions.network_builder.visualization import create_network_map


# Default link parameters
DEFAULT_LINK_PARAMETERS = {
    'Heat transmission main': {'flow_cap_max': 100000, 'flow_out_eff_per_distance': 1},
    'LQ heat distribution main': {'flow_cap_max': 100000, 'flow_out_eff_per_distance': 1},
    'LQ heat distribution secondary': {'flow_cap_max': 100000, 'flow_out_eff_per_distance': 1},
    'LV electricity distribution main': {'flow_cap_max': 100000, 'flow_out_eff_per_distance': 1},
    'LV electricity distribution secondary': {'flow_cap_max': 100000, 'flow_out_eff_per_distance': 1}
}


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
    debug_folder : str, optional
        Folder to save debug visualizations (default: 'debug')
    link_parameters : dict, optional
        Technical parameters for each link type (default: all 100000 kW, efficiency 1.0)
    transformer_supply_capacity : int, optional
        Maximum electricity supply capacity per transformer in kW (default: 100000)
    neighborhood_id : str, optional
        Neighborhood identifier for substation naming (e.g., 'multatulibuurt')
    substation_coords : list, optional
        [lon, lat] coordinates for the substation location
    
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
        - 'connectivity_info': Dict with connectivity statistics
    
    Side Effects:
    -------------
    - Saves 7 CSV files to output_folder/
    - If mode=='plot', saves network visualization to debug_folder/calliope_map.html
    """
    
    # Use default link parameters if not provided
    if link_parameters is None:
        link_parameters = DEFAULT_LINK_PARAMETERS.copy()
    
    # =========================================================================
    # STEP 1: Import base CSV files
    # =========================================================================
    warmtenet_links_carriers = pd.read_csv(os.path.join(inputs_folder, "warmtenet_links_carriers.csv"))
    warmtenet_nodes_techs = pd.read_csv(os.path.join(inputs_folder, "warmtenet_nodes_techs.csv"))
    warmtenet_nodes_coordinates = pd.read_csv(os.path.join(inputs_folder, "warmtenet_nodes_coordinates.csv"))
    warmtenet_links_techs = pd.read_csv(os.path.join(inputs_folder, "warmtenet_links_techs.csv"))
    
    # =========================================================================
    # STEP 2: Create all node types
    # =========================================================================
    
    # Create transformer nodes from GeoDataFrame
    transformer_nodes_coordinates, transformer_nodes_techs = create_transformer_nodes(
        stedin_transformers_gdf_delft, transformer_supply_capacity
    )
    
    # Create demand nodes
    demand_nodes, demand_techs, demand_coords = create_demand_nodes(
        merged_df, debug_single_node
    )
    
    # Create transmission nodes
    (heat_trans_nodes, elec_trans_nodes, 
     heat_trans_techs, elec_trans_techs,
     heat_trans_coords, elec_trans_coords) = create_transmission_nodes_df(
        heat_interp_gdf, elec_interp_gdf
    )
    
    # Combine all nodes
    nodes_techs, nodes_coordinates = combine_all_nodes(
        warmtenet_nodes_techs, warmtenet_nodes_coordinates,
        transformer_nodes_techs, transformer_nodes_coordinates,
        demand_techs, demand_coords,
        heat_trans_techs, elec_trans_techs,
        heat_trans_coords, elec_trans_coords
    )
    
    # =========================================================================
    # STEP 3: Create transmission links
    # =========================================================================
    heat_links_df, elec_links_df = create_transmission_links(
        stedin_heat_gdf_delft, stedin_elec_gdf_delft,
        heat_trans_nodes, elec_trans_nodes,
        link_parameters, spacing_m
    )
    
    # =========================================================================
    # STEP 4: Connect nodes to distribution network
    # =========================================================================
    
    # Create substation if coordinates provided
    warmtenet_to_substation_link = None
    substation_link = None
    
    if substation_coords is not None:
        substation_name = f"substation_{neighborhood_id}" if neighborhood_id else "substation_main"
        sub_lon, sub_lat = substation_coords[0], substation_coords[1]
        
        # Add substation node
        nodes_coordinates, nodes_techs = add_substation_node(
            nodes_coordinates, nodes_techs, substation_name, sub_lat, sub_lon
        )
        
        # Create substation links
        warmtenet_to_substation_link, substation_link, warmtenet_links_carriers = create_substation_links(
            substation_name, sub_lat, sub_lon,
            warmtenet_nodes_coordinates, heat_trans_nodes,
            warmtenet_links_carriers, link_parameters
        )
    
    # Connect transformers to electricity transmission
    transformer_links = create_transformer_to_elec_links(
        transformer_nodes_coordinates, elec_trans_nodes, link_parameters
    )
    
    # Connect demand nodes to nearest transmission nodes
    demand_heat_links, demand_elec_links = create_demand_to_transmission_links(
        demand_nodes, heat_trans_nodes, elec_trans_nodes, link_parameters
    )
    
    # Combine all links
    links_techs = combine_all_links(
        warmtenet_links_techs, heat_links_df, elec_links_df,
        warmtenet_to_substation_link, substation_link,
        transformer_links, demand_heat_links, demand_elec_links
    )
    
    # =========================================================================
    # STEP 5: Create carrier and cost DataFrames
    # =========================================================================
    links_LQ_heat, links_electricity = create_link_carriers(links_techs, warmtenet_links_carriers)
    links_costs = create_link_costs(links_techs)
    
    # =========================================================================
    # STEP 6: Ensure network connectivity
    # =========================================================================
    links_techs, isolated_demand_nodes, emergency_links = ensure_demand_connectivity(
        nodes_coordinates, links_techs, link_parameters, demand_nodes,
        heat_trans_nodes, haversine_distance
    )
    
    # Add emergency links to carriers and costs
    if isolated_demand_nodes:
        links_LQ_heat, links_electricity, links_costs = add_emergency_links_to_carriers(
            links_LQ_heat, links_electricity, links_costs, emergency_links
        )
    
    # =========================================================================
    # STEP 7: Export to CSV files
    # =========================================================================
    export_network_csvs(
        output_folder, warmtenet_links_carriers, nodes_techs,
        nodes_coordinates, links_techs, links_LQ_heat,
        links_electricity, links_costs
    )
    
    # =========================================================================
    # STEP 8: Generate visualization (if mode=='plot')
    # =========================================================================
    if mode == 'plot':
        create_network_map(nodes_coordinates, links_techs, debug_folder)
    
    # =========================================================================
    # Return all DataFrames
    # =========================================================================
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
