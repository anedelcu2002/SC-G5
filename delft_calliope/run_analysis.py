"""
District Heating Network Analysis - Main Workflow
Multatulibuurt, Delft, Netherlands


How to run:

cd delft_calliope
Basic: python run_analysis.py  
District heating (default): python run_analysis.py --scenario district_heating
Electrification: python run_analysis.py --scenario full_electrification
Export maps (default): python run_analysis.py --mode plot      
Don't export any maps (faster): python run_analysis.py --mode export 
Only use a single demand node (faster): python run_analysis.py --debug 
Node spacing in meters: python run_analysis.py --spacing 3.5

"""

import pandas as pd
import calliope
import time
import argparse

from functions.BAG_buildings_API import fetch_buildings_from_BAG
from functions.BAG_addresses_API import enrich_buildings_with_addresses
from functions.process_buildings import process_and_visualize_buildings
from functions.process_heat_demand import process_heat_demand
from functions.process_stedin_grids import process_stedin_grids
from functions.create_transmission_nodes import create_transmission_nodes
from functions.build_calliope_network import build_calliope_network
from functions.create_scenario_model import create_scenario_model
from functions.process_calliope_results import process_calliope_results


# =============================================================================
# CONFIGURATION
# =============================================================================

CONFIG = {
    # Run mode: 'plot' generates visualizations, 'export' skips visualization
    'mode': 'plot',
    
    # Heat demand scenario code for Multatulibuurt
    'area': '4011', # 4011 for medium demand, 4262 for high demand, 
    
    # BAG API key
    'BAG_API_KEY': 'l7c0673beb4a3f46e8a0caa164dc7b8397',
    
    # Polygon coordinates for Multatulibuurt (lon, lat pairs)
    'bbox_coords': [
        (4.3588444390090535, 51.98977145529007),
        (4.363727554070601, 51.99104189404924),
        (4.3599960417556245, 51.997399351063684),
        (4.356750677717929, 51.996732491653034),
        (4.354965562453528, 51.995617668217804),
        (4.358146528659458, 51.98999163382852),
        (4.3588444390090535, 51.98977145529007)
    ],
    
    # Node spacing for interpolation in meters (None = corner nodes only)
    'spacing_m': 3.5,
    
    # Scenario: 'district_heating' or 'full_electrification'
    'scenario': 'district_heating',
    
    # Debug mode: use only one demand node for faster testing
    'debug_single_node': False,
    
    # Data folders
    'data_tables_folder': 'data_tables',
    'outputs_folder': 'outputs',
    'debug_folder': 'debug',

    # Technology efficiencies
    'tech_efficiencies': {
        'heat_pump_cop': 4.0,          # Coefficient of Performance for air-source heat pumps
        'heat_substation_eff': 1.0     # Heat substation efficiency (HQ to LQ conversion)
    },

    # Postprocessing parameters for results analysis and bill of materials
    'postprocessing': {
        # Pipe sizing calculation parameters
        'pipe_sizing': {
            'heat_capacity': 4.19,      # Heat capacity in kJ/kgK
            'density': 1000,            # Density in kg/m3
            'delta_T': 25,              # Temperature difference in K
            'flow_speed': 0.62          # Flow speed in m/s
        },
        # Distance multiplication factors for each network segment type
        'distance_factors': {
            'Heat transmission main': 1.0,                  # HQ heat main network
            'LQ heat distribution main': 1.0,               # LQ heat backbone
            'LQ heat distribution secondary': 1.0,          # LQ heat to buildings
            'LV electricity distribution main': 1.0,        # Electricity backbone
            'LV electricity distribution secondary': 1.0    # Electricity to buildings
        }
    },

    # Link technical parameters for network segments
    'link_parameters': {
        'Heat transmission main': {
            'flow_cap_max': 10000,              # Maximum flow capacity (kW)
            'flow_out_eff_per_distance': 1      # Efficiency per distance unit
        },
        'LQ heat distribution main': {
            'flow_cap_max': 10000,
            'flow_out_eff_per_distance': 1
        },
        'LQ heat distribution secondary': {
            'flow_cap_max': 10000,
            'flow_out_eff_per_distance': 1
        },
        'LV electricity distribution main': {
            'flow_cap_max': 10000,
            'flow_out_eff_per_distance': 1
        },
        'LV electricity distribution secondary': {
            'flow_cap_max': 10000,
            'flow_out_eff_per_distance': 1
        }
    },

    # Transformer parameters
    'transformer_supply_capacity': 1000,  # Maximum electricity supply per transformer (kW)
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
    
    print("\n" + "="*80)
    print("DISTRICT HEATING NETWORK ANALYSIS - MULTATULIBUURT")
    print("="*80)
    print(f"Mode: {config['mode']}")
    print(f"Scenario: {config['scenario']}")
    print(f"Debug mode: {config['debug_single_node']}")
    print(f"Spacing: {config['spacing_m']}m")
    print("="*80 + "\n")
    
    # -------------------------------------------------------------------------
    # 1. Fetch building location data from BAG
    # -------------------------------------------------------------------------
    with Timer("API call to obtain building location data"):
        # Derive bounding_box from polygon coordinates
        lons = [coord[0] for coord in config['bbox_coords']]
        lats = [coord[1] for coord in config['bbox_coords']]
        config['bounding_box'] = [min(lons), min(lats), max(lons), max(lats)]
        all_buildings = fetch_buildings_from_BAG(
            config['bounding_box'], 
            config['BAG_API_KEY']
        )
    
    # -------------------------------------------------------------------------
    # 2. Fetch building address data from BAG
    # -------------------------------------------------------------------------
    with Timer("API call to obtain building address data"):
        building_addresses = enrich_buildings_with_addresses(
            all_buildings, 
            config['BAG_API_KEY']
        )
    
    # -------------------------------------------------------------------------
    # 3. Create building dataframe and visualize
    # -------------------------------------------------------------------------
    with Timer("Create building dataframe and visualize"):
        buildings_df = process_and_visualize_buildings(
            all_buildings, 
            building_addresses, 
            mode=config['mode']
        )
    
    # -------------------------------------------------------------------------
    # 4. Define and visualize demand nodes
    # -------------------------------------------------------------------------
    with Timer("Define and visualize demand nodes"):
        merged_df, buildings_gdf = process_heat_demand(
            buildings_df, 
            config['area'], 
            mode=config['mode']
        )
    
    # -------------------------------------------------------------------------
    # 5. Load and process Stedin grid data
    # -------------------------------------------------------------------------
    with Timer("API call to obtain and process Stedin grid data"):
        stedin_heat_gdf_delft, stedin_elec_gdf_delft, stedin_transformers_gdf_delft = process_stedin_grids(
            bbox_coords=config['bbox_coords'],
            buildings_df=buildings_df,  # NEW: Pass buildings
            features_to_remove_heat=config.get('features_to_remove_heat'),  # Now optional
            features_to_remove_elec=config.get('features_to_remove_elec'),  # Now optional
            mode=config['mode']
        )
        
    # -------------------------------------------------------------------------
    # 6. Create transmission nodes
    # -------------------------------------------------------------------------
    with Timer("Create transmission nodes"):
        heat_interp_gdf, elec_interp_gdf = create_transmission_nodes(
            stedin_heat_gdf_delft, 
            stedin_elec_gdf_delft, 
            spacing_m=config['spacing_m']
        )
    
    # -------------------------------------------------------------------------
    # 7. Build Calliope network structure
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
            inputs_folder=config['data_tables_folder'].replace('data_tables', 'inputs'),
            output_folder=config['data_tables_folder'],
            link_parameters=config['link_parameters'],
            transformer_supply_capacity=config['transformer_supply_capacity']
        )
    # -------------------------------------------------------------------------
    # 8. Create scenario and configure model
    # -------------------------------------------------------------------------
    with Timer("Create scenario and configure model"):
        model = create_scenario_model(
            scenario=config['scenario'],
            data_tables_folder=config['data_tables_folder'],
            tech_efficiencies=config['tech_efficiencies']
        )
    
    # -------------------------------------------------------------------------
    # 9. Build Calliope model
    # -------------------------------------------------------------------------
    with Timer("Build Calliope model"):
        model.build()
    
    # -------------------------------------------------------------------------
    # 10. Solve Calliope model
    # -------------------------------------------------------------------------
    with Timer("Solve Calliope model"):
        model.solve()
    
    # -------------------------------------------------------------------------
    # 11. Process Calliope results
    # -------------------------------------------------------------------------
    with Timer("Process Calliope results"):
        final_export_df = process_calliope_results(
            model=model,
            buildings_gdf=buildings_gdf,
            mode=config['mode'],
            output_folder=config['outputs_folder'],
            heat_capacity=config['postprocessing']['pipe_sizing']['heat_capacity'],
            density=config['postprocessing']['pipe_sizing']['density'],
            delta_T=config['postprocessing']['pipe_sizing']['delta_T'],
            flow_speed=config['postprocessing']['pipe_sizing']['flow_speed'],
            distance_factors=config['postprocessing']['distance_factors']
        )
    
    return model, final_export_df


# =============================================================================
# COMMAND LINE INTERFACE
# =============================================================================

def parse_arguments():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        description='District Heating Network Analysis for Multatulibuurt, Delft'
    )
    
    parser.add_argument(
        '--scenario',
        type=str,
        choices=['district_heating', 'full_electrification'],
        default=CONFIG['scenario'],
        help='Scenario to run (default: district_heating)'
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
    
    return parser.parse_args()


# =============================================================================
# ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    # Parse command line arguments
    args = parse_arguments()
    
    # Update config with command line arguments
    CONFIG['scenario'] = args.scenario
    CONFIG['mode'] = args.mode
    CONFIG['debug_single_node'] = args.debug
    CONFIG['spacing_m'] = args.spacing
    
    # Run main workflow
    try:
        model, results = main(CONFIG)
        print("\nAnalysis completed successfully!\n")
    except Exception as e:
        print(f"\nERROR: Analysis failed with exception:")
        print(f"{type(e).__name__}: {e}\n")
        raise
