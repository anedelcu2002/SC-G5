"""
Main workflow script for analysis of an individual Delft neighborhood's
heating system using Calliope.

Usage:
    cd delft_calliope
    
    # Run with default settings (uses run_analysis_config.yaml)
    python run_analysis.py
    
    # Run with custom config file
    python run_analysis.py --config my_config.yaml
    
    # List available neighborhoods
    python run_analysis.py --list-neighborhoods
    
    # Override specific settings via command line
    python run_analysis.py --neighborhood holstbuurt --year 2019
    python run_analysis.py --scenario full_electrification
    python run_analysis.py --mode export  # Fast mode without visualizations
    python run_analysis.py --debug  # Debug mode with single demand node
    
    # Online mode (requires BAG API key)
    python run_analysis.py --online --bag-api-key YOUR_KEY

Configuration (run_analysis_config.yaml):
    scenario:
        neighborhood: Which neighborhood to analyze
        year: Heat demand year (2013=cold, 2019=normal, 2020=warm)
        type: 'district_heating', 'full_electrification', or 'hybrid'
        topology_source: 'stedin' or 'osm'
    
    execution:
        mode: 'plot' (with visualizations) or 'export' (faster)
        debug_single_node: Use single node for testing
        spacing_m: Node spacing in meters
    
    data_sources:
        online: Fetch from APIs (true) or use cache (false)
        bag_api_key: Required for online mode
    
    paths:
        Input/output folder locations
    
    tech_efficiencies:
        heat_pump_cop: Heat pump coefficient of performance
        heat_substation_eff: Substation efficiency (0-1)
        hybrid_threshold_kW: Threshold for hybrid scenario
    
    postprocessing:
        pipe_sizing: Parameters for pipe diameter calculation
        distance_factors: Length multipliers per network segment
        heat_loss_rates: Heat losses in W/m per segment type
        electricity_resistance_rates: Resistance in Ω/km per cable type

Output:
    Results are saved to the outputs folder including:
    - scenario_summary.json: Comprehensive results summary
    - Various CSV files with detailed network data
    - Visualizations (if mode='plot')
"""

import pandas as pd
import calliope
import os

# Configuration
from functions.config import (
    load_config,
    get_neighborhood_params,
    list_available_neighborhoods,
    parse_arguments,
    DEFAULT_CONFIG_PATH,
    apply_cli_overrides,
    validate_online_mode
)

# Data acquisition
from functions.data_acquisition import (
    fetch_buildings_from_BAG,
    load_buildings_from_cache,
    enrich_buildings_with_addresses
)

# Data processing
from functions.data_processing import (
    process_and_visualize_buildings,
    process_heat_demand
)

# Network topology
from functions.network_topology import (
    process_network_topology,
    create_transmission_nodes
)

# Network builder
from functions.network_builder import build_calliope_network

# Model
from functions.model import create_scenario_model

# Results processing
from functions.results_processing import process_calliope_results

# Output
from functions.output import (
    save_scenario_summary,
    Timer,
    execution_times,
    print_timing_summary
)


# =============================================================================
# MAIN WORKFLOW
# =============================================================================

def main(config):
    """
    Run complete district heating network analysis workflow
    
    Parameters:
    -----------
    config : dict
        Configuration dictionary with all parameters
    """
    
    # Load neighborhood-specific parameters
    try:
        neighborhood_params = get_neighborhood_params(
            config['neighborhood'],
            config['year']
        )
    except ValueError as e:
        print(f"\nERROR: {e}")
        print("\nAvailable neighborhoods:")
        neighborhoods = list_available_neighborhoods()
        for nbh_id, details in neighborhoods.items():
            print(f"  - {nbh_id}: {details['name']} (years: {', '.join(map(str, details['years']))})")
        raise
    
    # Update config with neighborhood-specific parameters
    config['area'] = neighborhood_params['area']
    config['year'] = neighborhood_params['year']
    config['bbox_coords'] = neighborhood_params['bbox_coords']
    config['neighborhood_name'] = neighborhood_params['name']
    config['substation_coords'] = neighborhood_params['substation_coords']
    config['neighborhood_id'] = neighborhood_params['neighborhood_id']
    
    print("\n" + "="*80)
    print(f"DISTRICT HEATING NETWORK ANALYSIS - {neighborhood_params['name'].upper()}")
    print("="*80)
    print(f"Neighborhood: {config['neighborhood']} ({neighborhood_params['name']})")
    print(f"Year: {config['year']}")
    print(f"Heat demand area code: {config['area']}")
    print(f"Substation coordinates: {config['substation_coords']}")
    print(f"Mode: {config['mode']}")
    print(f"Scenario: {config['scenario']}")
    print(f"Debug mode: {config['debug_single_node']}")
    print(f"Spacing: {config['spacing_m']}m")
    print("="*80 + "\n")
    
    # -------------------------------------------------------------------------
    # 1. Fetch building data from BAG (or load from cache)
    # -------------------------------------------------------------------------
    # Derive bounding_box from polygon coordinates
    lons = [coord[0] for coord in config['bbox_coords']]
    lats = [coord[1] for coord in config['bbox_coords']]
    config['bounding_box'] = [min(lons), min(lats), max(lons), max(lats)]
    
    with Timer("Obtain building location and address data"):
        if config['online']:
            # Online mode: Fetch from BAG API
            all_buildings = fetch_buildings_from_BAG(
                config['bounding_box'], 
                api_key=config['BAG_API_KEY']
            )
            building_addresses = enrich_buildings_with_addresses(
                all_buildings, 
                api_key=config['BAG_API_KEY']
            )
        else:
            # Offline mode: Load from cache and filter to bounding box
            all_buildings, building_addresses = load_buildings_from_cache(
                config['bounding_box'],
                cache_path=config['bag_cache_path']
            )
    
    # -------------------------------------------------------------------------
    # 2. Create building dataframe and visualize
    # -------------------------------------------------------------------------
    with Timer("Create building dataframe and visualize"):
        buildings_df = process_and_visualize_buildings(
            all_buildings, 
            building_addresses, 
            mode=config['mode'],
            debug_folder=config['debug_folder']
        )
    
    # -------------------------------------------------------------------------
    # 3. Define and visualize demand nodes
    # -------------------------------------------------------------------------
    with Timer("Define and visualize demand nodes"):
        merged_df, buildings_gdf = process_heat_demand(
            buildings_df, 
            config['area'], 
            config['year'],
            mode=config['mode'],
            online=config['online'],
            csv_path=config['heat_demand_csv_path'],
            debug_folder=config['debug_folder']
        )
    # -------------------------------------------------------------------------
    # 4. Load and process network topology (Stedin or OSM)
    # -------------------------------------------------------------------------
    with Timer(f"Load and process network topology ({config['topology_source'].upper()})"):
        stedin_heat_gdf_delft, stedin_elec_gdf_delft, stedin_transformers_gdf_delft = process_network_topology(
            bbox_coords=config['bbox_coords'],
            buildings_df=buildings_df,
            topology_source=config['topology_source'],
            osm_pbf_path='inputs/delft.osm.pbf',
            online=config['online'],  
            cache_path=config['stedin_cache_path'],  
            mode=config['mode'],
            debug_folder=config['debug_folder']
        )
        
    # -------------------------------------------------------------------------
    # 5. Create transmission nodes
    # -------------------------------------------------------------------------
    with Timer("Create transmission nodes"):
        heat_interp_gdf, elec_interp_gdf = create_transmission_nodes(
            stedin_heat_gdf_delft, 
            stedin_elec_gdf_delft, 
            spacing_m=config['spacing_m']
        )
    
    # -------------------------------------------------------------------------
    # 6. Build Calliope network structure
    # -------------------------------------------------------------------------
    with Timer("Build Calliope network"):
        network_dfs = build_calliope_network(
            merged_df=merged_df,
            heat_interp_gdf=heat_interp_gdf,
            elec_interp_gdf=elec_interp_gdf,
            stedin_heat_gdf_delft=stedin_heat_gdf_delft,
            stedin_elec_gdf_delft=stedin_elec_gdf_delft,
            stedin_transformers_gdf_delft=stedin_transformers_gdf_delft,
            spacing_m=config['spacing_m'],
            mode=config['mode'],
            debug_single_node=config['debug_single_node'],
            inputs_folder=config['inputs_folder'],
            output_folder=config['data_tables_folder'],
            debug_folder=config['debug_folder'],
            link_parameters=config['link_parameters'],
            transformer_supply_capacity=config['transformer_supply_capacity'],
            neighborhood_id=config['neighborhood_id'],       
            substation_coords=config['substation_coords']
        )
        
        # Extract connectivity info
        connectivity_info = network_dfs.get('connectivity_info', {
            'num_isolated_demand_nodes': 0,
            'isolated_demand_nodes': [],
            'total_demand_nodes': 0
        })
    # -------------------------------------------------------------------------
    # 7. Create scenario and configure model
    # -------------------------------------------------------------------------
    with Timer("Create scenario and configure model"):
        model = create_scenario_model(
            scenario=config['scenario'],
            data_tables_folder=config['data_tables_folder'],
            tech_efficiencies=config['tech_efficiencies'],
            neighborhood_id=config['neighborhood_id']       
        )
    
    # -------------------------------------------------------------------------
    # 8. Build Calliope model
    # -------------------------------------------------------------------------
    with Timer("Build Calliope model"):
        model.build()
    
    # -------------------------------------------------------------------------
    # 9. Solve Calliope model
    # -------------------------------------------------------------------------
    with Timer("Solve Calliope model"):
        model.solve()
    
    # -------------------------------------------------------------------------
    # 10. Process Calliope results
    # -------------------------------------------------------------------------
    with Timer("Process Calliope results"):
        (final_export_df, total_system_losses_kw, total_electricity_losses_kw, supply_losses, 
         total_unmet_demand_kw, num_unmet_nodes, total_demand_nodes,
         total_LQ_losses_kw, total_HQ_losses_kw, substation_efficiency_losses_kw) = process_calliope_results(
            model=model,
            buildings_gdf=buildings_gdf,
            mode=config['mode'],
            output_folder=config['outputs_folder'],
            heat_capacity=config['postprocessing']['pipe_sizing']['heat_capacity'],
            density=config['postprocessing']['pipe_sizing']['density'],
            delta_T=config['postprocessing']['pipe_sizing']['delta_T'],
            flow_speed=config['postprocessing']['pipe_sizing']['flow_speed'],
            distance_factors=config['postprocessing']['distance_factors'],
            pipe_sizing_method=config['postprocessing']['pipe_sizing_method'],
            heat_loss_rates=config['postprocessing'].get('heat_loss_rates'),
            apply_heat_losses=config['postprocessing'].get('apply_heat_losses', False),
            electricity_resistance_rates=config['postprocessing'].get('electricity_resistance_rates'),
            apply_electricity_losses=config['postprocessing'].get('apply_electricity_losses', False),
            substation_efficiency=config['tech_efficiencies']['heat_substation_eff']   
        )
            
    # -------------------------------------------------------------------------
    # 11. Save scenario summary
    # -------------------------------------------------------------------------
    with Timer("Save scenario summary"):
        scenario_summary = save_scenario_summary(
            config=config,
            model=model,
            results_df=final_export_df,
            output_folder=config['outputs_folder'],
            execution_times=execution_times,
            apply_heat_losses=config['postprocessing'].get('apply_heat_losses', False),
            total_system_losses_kw=total_system_losses_kw,
            total_LQ_losses_kw=total_LQ_losses_kw,
            total_HQ_losses_kw=total_HQ_losses_kw,
            substation_efficiency_losses_kw=substation_efficiency_losses_kw,
            apply_electricity_losses=config['postprocessing'].get('apply_electricity_losses', False),
            total_electricity_losses_kw=total_electricity_losses_kw,
            supply_losses=supply_losses,
            total_unmet_demand_kw=total_unmet_demand_kw,
            num_unmet_nodes=num_unmet_nodes,
            total_demand_nodes=total_demand_nodes,
            connectivity_info=connectivity_info
        )
    
    return model, final_export_df


# =============================================================================
# ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    import json
    from datetime import datetime
    
    # Parse command line arguments
    args = parse_arguments()
    
    # Handle --list-neighborhoods flag (doesn't need config)
    if args.list_neighborhoods:
        print("\nAvailable neighborhoods:\n")
        neighborhoods = list_available_neighborhoods()
        for nbh_id, details in neighborhoods.items():
            print(f"  {nbh_id}:")
            print(f"    Name: {details['name']}")
            print(f"    Years: {', '.join(map(str, details['years']))}")
            print()
        exit(0)
    
    # Check config file exists
    if not os.path.exists(args.config):
        print(f"ERROR: Configuration file not found: {args.config}")
        exit(1)
    
    # Load configuration from YAML file
    print(f"Loading configuration from: {args.config}")
    CONFIG = load_config(args.config)
    
    # Validate online mode has required API key
    is_valid, error_msg = validate_online_mode(args)
    if not is_valid:
        print(error_msg)
        exit(1)
    
    # Apply CLI argument overrides to config
    CONFIG = apply_cli_overrides(CONFIG, args)

    # Run main workflow
    try:
        model, results = main(CONFIG)
        print_timing_summary()
        print("\nAnalysis completed successfully!\n")
    except Exception as e:
        print(f"\nERROR: Analysis failed with exception:")
        print(f"{type(e).__name__}: {e}\n")

        try:
            error_summary = {
                'scenario_info': {
                    'neighborhood': CONFIG['neighborhood'],
                    'year': CONFIG['year'],
                    'scenario_type': CONFIG['scenario'],
                    'topology_source': CONFIG['topology_source'],
                    'timestamp': datetime.now().isoformat(),
                },
                'status': 'FAILED',
                'error': {
                    'type': type(e).__name__,
                    'message': str(e)
                },
                'execution_times': execution_times
            }
            
            output_path = os.path.join(CONFIG['outputs_folder'], 'scenario_summary.json')
            os.makedirs(CONFIG['outputs_folder'], exist_ok=True)
            with open(output_path, 'w') as f:
                json.dump(error_summary, f, indent=2, default=str)
            
            print(f"Error summary saved to: {output_path}")
        except:
            pass  # If summary save fails, don't mask the original error
        
        raise
