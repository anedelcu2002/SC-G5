"""
District Heating Network Analysis - Main Workflow
Delft Neighborhoods: Multatulibuurt, Holstbuurt, Mythologiebuurt, Poptahof-Zuid

How to run:

cd delft_calliope

# List available neighborhoods
python run_analysis.py --list-neighborhoods

# Run with default settings (Multatulibuurt, 2019, district heating)
python run_analysis.py

# Run for a different neighborhood
python run_analysis.py --neighborhood holstbuurt --year 2019

# Run with full electrification scenario
python run_analysis.py --scenario full_electrification

# Run with hybrid scenario
python run_analysis.py --scenario hybrid

# Fast mode without visualizations
python run_analysis.py --mode export

# Debug mode with single demand node
python run_analysis.py --debug

"""

import pandas as pd
import calliope
import time
import argparse
import yaml

from functions.BAG_buildings_API import fetch_buildings_from_BAG, load_buildings_from_cache
from functions.BAG_addresses_API import enrich_buildings_with_addresses
from functions.process_buildings import process_and_visualize_buildings
from functions.process_heat_demand import process_heat_demand
from functions.create_transmission_nodes import create_transmission_nodes
from functions.build_calliope_network import build_calliope_network
from functions.create_scenario_model import create_scenario_model
from functions.process_calliope_results import process_calliope_results
from functions.load_neighborhood_config import get_neighborhood_params, list_available_neighborhoods
from functions.process_stedin_grids import process_network_topology
from functions.save_summary import save_scenario_summary


# =============================================================================
# CONFIGURATION
# =============================================================================

CONFIG = {
    # Neighborhood and year selection
    'neighborhood': 'multatulibuurt',
    'year': 2019,
    
    # Run mode: 'plot' generates visualizations, 'export' skips visualization
    'mode': 'plot',

    # Network topology source: 'stedin' (default) or 'osm' (OpenStreetMap roads)
    'topology_source': 'stedin',
    
    # BAG API key
    'BAG_API_KEY': 'l7c0673beb4a3f46e8a0caa164dc7b8397',
    
    # Node spacing for interpolation in meters (None = corner nodes only)
    'spacing_m': 5,
    
    # Scenario: 'district_heating' or 'full_electrification' or 'hybrid'
    'scenario': 'district_heating',
    
    # Debug mode: use only one demand node for faster testing
    'debug_single_node': False,
    
    # Data source mode: True = fetch from APIs, False = load from cached files
    'online': False,  # When False, uses cached files for all data inputs
    'heat_demand_csv_path': 'inputs/heat_demand_cache',  # Path to heat demand CSV cache
    'bag_cache_path': 'inputs/bag_cache',  # Path to BAG pickle cache
    'stedin_cache_path': 'inputs/stedin_cache',  # Path to Stedin pickle cache

    # Data folders
    'data_tables_folder': 'data_tables',
    'outputs_folder': 'outputs',
    'debug_folder': 'debug',
    'inputs_folder': 'inputs',

    # Technology efficiencies
    'tech_efficiencies': {
        'heat_pump_cop': 4.0,
        'heat_substation_eff': 1.0,
        'hybrid_threshold_kW': 50
    },

    # Postprocessing parameters for results analysis and bill of materials
    'postprocessing': {
        'pipe_sizing': {
            'heat_capacity': 4.19,
            'density': 1000,
            'delta_T': 25,
            'flow_speed': 0.62
        },
        'pipe_sizing_method': 'individual',
        'distance_factors': {
            'Heat transmission main': 1.0,
            'LQ heat distribution main': 1.0,
            'LQ heat distribution secondary': 1.0,
            'LV electricity distribution main': 1.0,
            'LV electricity distribution secondary': 1.0
        },
        'heat_loss_rates': {
            'Heat transmission main': 20.0,       # W/m
            'LQ heat distribution main': 15.0,    # W/m
            'LQ heat distribution secondary': 10.0 # W/m
        },
        'apply_heat_losses': True
    },

    # Link technical parameters for network segments
    'link_parameters': {
        'Heat transmission main': {
            'flow_cap_max': 100000,
            'flow_out_eff_per_distance': 1
        },
        'LQ heat distribution main': {
            'flow_cap_max': 100000,
            'flow_out_eff_per_distance': 1
        },
        'LQ heat distribution secondary': {
            'flow_cap_max': 100000,
            'flow_out_eff_per_distance': 1
        },
        'LV electricity distribution main': {
            'flow_cap_max': 100000,
            'flow_out_eff_per_distance': 1
        },
        'LV electricity distribution secondary': {
            'flow_cap_max': 100000,
            'flow_out_eff_per_distance': 1
        }
    },

    'transformer_supply_capacity': 100000,
}


# =============================================================================
# TIMING INFRASTRUCTURE
# =============================================================================

execution_times = {}

class Timer:
    """Context manager for timing code blocks"""
    def __init__(self, name):
        self.name = name
    
    def __enter__(self):
        self.start = time.perf_counter()
        return self
    
    def __exit__(self, *args):
        self.end = time.perf_counter()
        elapsed = self.end - self.start
        execution_times[self.name] = elapsed
        print(f" {self.name}: {elapsed:.3f}s")


def print_timing_summary():
    """Print comprehensive timing analysis"""
    if execution_times:
        timing_df = pd.DataFrame({
            'Operation': list(execution_times.keys()),
            'Time (s)': list(execution_times.values())
        })
        timing_df['% of Total'] = (timing_df['Time (s)'] / timing_df['Time (s)'].sum() * 100).round(2)
        timing_df = timing_df.sort_values('Time (s)', ascending=False)
        
        print("\n" + "="*80)
        print("EXECUTION TIME SUMMARY")
        print("="*80)
        print(timing_df.to_string(index=False))
        print("="*80)
        print(f"Total Execution Time: {timing_df['Time (s)'].sum():.3f}s")
        print("="*80 + "\n")
    else:
        print("No timing data collected.")


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
                config['BAG_API_KEY']
            )
            building_addresses = enrich_buildings_with_addresses(
                all_buildings, 
                config['BAG_API_KEY']
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
            mode=config['mode']
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
            csv_path=config['heat_demand_csv_path']
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
            mode=config['mode']
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
            link_parameters=config['link_parameters'],
            transformer_supply_capacity=config['transformer_supply_capacity'],
            neighborhood_id=config['neighborhood_id'],       
            substation_coords=config['substation_coords']    
        )
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
        final_export_df, total_system_losses_kw, supply_losses = process_calliope_results(
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
            apply_heat_losses=config['postprocessing'].get('apply_heat_losses', False)
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
            supply_losses=supply_losses
        )
    
    return model, final_export_df


# =============================================================================
# COMMAND LINE INTERFACE
# =============================================================================

def parse_arguments():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        description='District Heating Network Analysis for Delft Neighborhoods'
    )
    
    parser.add_argument(
        '--neighborhood',
        type=str,
        default=CONFIG['neighborhood'],
        help=f"Neighborhood to analyze (default: {CONFIG['neighborhood']}). "
             f"Available: multatulibuurt, holstbuurt, mythologiebuurt, poptahofzuid"
    )
    
    parser.add_argument(
        '--year',
        type=int,
        default=CONFIG['year'],
        help='Year for heat demand data (default: 2019). Available: 2013 (cold), 2019 (normal), 2020 (warm)'
    )
    
    parser.add_argument('--scenario', 
        type=str, 
        default=CONFIG['scenario'],
        help="Scenario type: 'district_heating', 'full_electrification', or 'hybrid'"
    )
    
    parser.add_argument('--threshold', 
        type=float, 
        default=CONFIG['tech_efficiencies']['hybrid_threshold_kW'],
        help="Demand threshold in kW for hybrid scenario (default: 50)"
    )
    
    parser.add_argument(
        '--mode',
        type=str,
        choices=['plot', 'export'],
        default=CONFIG['mode'],
        help='Run mode: plot generates visualizations, export skips them (default: plot)'
    )
    
    parser.add_argument(
        '--debug',
        action='store_true',
        help='Debug mode: use only one demand node for faster testing'
    )
    
    parser.add_argument(
        '--spacing',
        type=float,
        default=CONFIG['spacing_m'],
        help='Node spacing in meters (default: 3.5)'
    )
    
    parser.add_argument(
        '--list-neighborhoods',
        action='store_true',
        help='List all available neighborhoods and exit'
    )

    parser.add_argument(
        '--topology_source',
        type=str,
        choices=['stedin', 'osm'],
        default='stedin',
        help="Network topology source: 'stedin' (grid data) or 'osm' (OpenStreetMap roads)"
    )

    parser.add_argument(
        '--pipe-sizing',
        type=str,
        choices=['class', 'individual'],
        default='individual',
        help="Pipe sizing method: 'class' (uniform per type) or 'individual' (per pipe)"
    )

    parser.add_argument(
        '--output-folder',
        type=str,
        default=CONFIG['outputs_folder'],
        help="Output folder for results (default: 'outputs')"
    )
    
    parser.add_argument(
        '--data-tables-folder',
        type=str,
        default=CONFIG['data_tables_folder'],
        help="Data tables folder for intermediate CSV files (default: 'data_tables')"
    )

    parser.add_argument('--offline', 
        action='store_true',
        default=True,
        help='Use cached files for both heat demand and BAG building data instead of APIs'
    )
    
    return parser.parse_args()


# =============================================================================
# ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    # Parse command line arguments
    args = parse_arguments()
    
    # Handle --list-neighborhoods flag
    if args.list_neighborhoods:
        print("\nAvailable neighborhoods:\n")
        neighborhoods = list_available_neighborhoods()
        for nbh_id, details in neighborhoods.items():
            print(f"  {nbh_id}:")
            print(f"    Name: {details['name']}")
            print(f"    Years: {', '.join(map(str, details['years']))}")
            print()
        exit(0)
    
    # Update config with command line arguments
    CONFIG['neighborhood'] = args.neighborhood
    CONFIG['year'] = args.year
    CONFIG['scenario'] = args.scenario
    CONFIG['mode'] = args.mode
    CONFIG['debug_single_node'] = args.debug
    CONFIG['spacing_m'] = args.spacing
    if args.topology_source:
        CONFIG['topology_source'] = args.topology_source
    if args.threshold:
        CONFIG['tech_efficiencies']['hybrid_threshold_kW'] = args.threshold
    if args.output_folder:
        CONFIG['outputs_folder'] = args.output_folder
    if args.data_tables_folder:
        CONFIG['data_tables_folder'] = args.data_tables_folder
    if args.offline:
        CONFIG['online'] = False

    # Run main workflow
    try:
        model, results = main(CONFIG)
        print("\nAnalysis completed successfully!\n")
    except Exception as e:
        print(f"\nERROR: Analysis failed with exception:")
        print(f"{type(e).__name__}: {e}\n")

        try:
            import os
            import json
            from datetime import datetime
            
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
        
