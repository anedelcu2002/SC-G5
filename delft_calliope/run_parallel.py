"""
Parallel scenario execution script for heating system modeling in the neighborhoods of Delft.
Can run multiple neighborhoods, years, scenarios, and topology sources in parallel,
or study the sensitivity of the outputs to various parameters by varying them one at a time.

Usage:
    python run_parallel.py
    python run_parallel.py --config path/to/config.yaml

    The script will prompt for confirmation before executing. Run from the
    delft_calliope directory where run_analysis.py is located.

Configuration:
    Edit config.yaml (or specify a custom config file) to customize:
    - scenarios: neighborhoods, years, heating_scenarios, topology_sources
    - parameters: ranges for sensitivity analysis
    - execution: max_workers, mode, timeout settings
    - baselines: baseline configurations for DH and electrification

Output:
    Results are saved to parallel_results/<timestamp>/ including:
    - execution_summary.csv/json: Run metadata and status
    - scenario_summary.csv: Aggregated results from all scenarios
    - Individual run folders with full outputs and parameters

Dependencies:
    - pandas
    - pyyaml
    - run_analysis.py (must be in the same directory)
"""

import os
import subprocess
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
import pandas as pd
import json
import time
import random
import hashlib
import yaml
import argparse

# =============================================================================
# Configuration loading from YAML
# =============================================================================

def load_config(config_path='config.yaml'):
    """
    Load configuration from YAML file.
    
    Parameters
    ----------
    config_path : str
        Path to the YAML configuration file
    
    Returns
    -------
    dict
        Configuration dictionary
    """
    with open(config_path, 'r') as f:
        return yaml.safe_load(f)

# Default config path (can be overridden via command line)
CONFIG_PATH = 'config.yaml'

def init_config(config_path=None):
    """
    Initialize global configuration variables from YAML config.
    
    Parameters
    ----------
    config_path : str, optional
        Path to config file. Uses CONFIG_PATH if not specified.
    """
    global NEIGHBORHOODS, YEARS, SCENARIOS, TOPOLOGY_SOURCES, SPACING_M
    global HEAT_SUBSTATION_EFF, DELTA_T, FLOW_SPEED
    global DISTANCE_FACTOR_HEAT_TRANS_MAIN, DISTANCE_FACTOR_HEAT_DIST_MAIN, DISTANCE_FACTOR_HEAT_DIST_SEC
    global HEAT_LOSS_RATE_TRANS_MAIN, HEAT_LOSS_RATE_DIST_MAIN, HEAT_LOSS_RATE_DIST_SEC
    global DISTANCE_FACTOR_ELEC_DIST_MAIN, DISTANCE_FACTOR_ELEC_DIST_SEC
    global ELEC_RESISTANCE_MAIN, ELEC_RESISTANCE_SEC, HEAT_PUMP_COP
    global APPLY_HEAT_LOSSES, APPLY_ELECTRICITY_LOSSES
    global MAX_WORKERS, MODE, RESULTS_BASE_DIR, TIMEOUT_SECONDS
    global BASELINE_DH, BASELINE_ELEC, TIMESTAMP
    
    if config_path is None:
        config_path = CONFIG_PATH
    
    config = load_config(config_path)
    
    # =============================================================================
    # High-level configuration: neighborhoods, demand scenarios, alternative heating systems, topology sources
    # =============================================================================
    
    # Define all parameter combinations to run
    NEIGHBORHOODS = config['scenarios']['neighborhoods']
    YEARS = config['scenarios']['years']
    SCENARIOS = config['scenarios']['heating_scenarios']
    TOPOLOGY_SOURCES = config['scenarios']['topology_sources']
    SPACING_M = config['parameters']['spacing_m']  # Node spacing in meters
    
    # =============================================================================
    # Low-level configuration: parameter ranges for sensitivity analysis
    # =============================================================================
    
    # District heating parameters
    dh = config['parameters']['district_heating']
    HEAT_SUBSTATION_EFF = dh['heat_substation_eff']  # Heat substation efficiency
    DELTA_T = dh['delta_t']  # Temperature difference for pipe sizing (°C)
    FLOW_SPEED = dh['flow_speed']  # Flow speed for pipe sizing (m/s)
    DISTANCE_FACTOR_HEAT_TRANS_MAIN = dh['distance_factors']['trans_main']  # no variation, Warmtenet route known
    DISTANCE_FACTOR_HEAT_DIST_MAIN = dh['distance_factors']['dist_main']  # 10% variation
    DISTANCE_FACTOR_HEAT_DIST_SEC = dh['distance_factors']['dist_sec']  # 10% variation
    HEAT_LOSS_RATE_TRANS_MAIN = dh['heat_loss_rates']['trans_main']  # 10% variation
    HEAT_LOSS_RATE_DIST_MAIN = dh['heat_loss_rates']['dist_main']  # 10% variation
    HEAT_LOSS_RATE_DIST_SEC = dh['heat_loss_rates']['dist_sec']  # 10% variation
    
    # Heat pump parameters
    elec = config['parameters']['electrification']
    DISTANCE_FACTOR_ELEC_DIST_MAIN = elec['distance_factors']['dist_main']  # 10% variation
    DISTANCE_FACTOR_ELEC_DIST_SEC = elec['distance_factors']['dist_sec']  # 10% variation
    ELEC_RESISTANCE_MAIN = elec['elec_resistance']['main']  # 10% variation
    ELEC_RESISTANCE_SEC = elec['elec_resistance']['sec']  # 10% variation
    HEAT_PUMP_COP = elec['heat_pump_cop']  # Heat pump coefficient of performance, variation based on CE Delft assumptions
    
    # =============================================================================
    # Run configuration: execution mode, parallel workers, output organization
    # =============================================================================
    
    # Enable or disable transmission losses
    APPLY_HEAT_LOSSES = config['execution']['apply_heat_losses']  # Set to [True, False] to test both
    APPLY_ELECTRICITY_LOSSES = config['execution']['apply_electricity_losses']  # Set to [True, False] to test both
    
    # Number of parallel scenario runs, run mode
    MAX_WORKERS = config['execution']['max_workers']  # Can be set to up to 16 for 16-core CPU, but your RAM must handle it
    MODE = config['execution']['mode']  # Use 'export' to skip visualizations for faster execution
    TIMEOUT_SECONDS = config['execution'].get('timeout_seconds', 3600)
    
    # Output directory
    RESULTS_BASE_DIR = config['execution']['results_base_dir']
    TIMESTAMP = datetime.now().strftime('%Y%m%d_%H%M%S')
    
    # Baseline configurations for sensitivity study
    BASELINE_DH = config['baselines']['district_heating']
    BASELINE_ELEC = config['baselines']['electrification']


# =============================================================================
# Sensitivity analysis combination generation function
# =============================================================================

def _get_param_index(param_name):
    """
    Get the tuple index for a parameter name.
    
    Maps parameter names to their position in the combination tuple used
    by run_single_scenario(). Used internally when modifying specific
    parameters in sensitivity analysis.
    
    Parameters
    ----------
    param_name : str
        Name of the parameter (e.g., 'spacing_m', 'heat_pump_cop')
    
    Returns
    -------
    int
        Index position in the parameter tuple
    
    Raises
    ------
    ValueError
        If param_name is not in the parameter order list
    """
    param_order = [
        'neighborhood', 'year', 'scenario', 'topology_source',
        'spacing_m', 'heat_pump_cop', 'heat_substation_eff',
        'delta_t', 'flow_speed',
        'distance_factor_heat_trans_main', 'distance_factor_heat_dist_main',
        'distance_factor_heat_dist_sec', 'distance_factor_elec_dist_main',
        'distance_factor_elec_dist_sec',
        'apply_heat_losses', 'apply_electricity_losses',
        'heat_loss_rate_trans_main', 'heat_loss_rate_dist_main',
        'heat_loss_rate_dist_sec',
        'elec_resistance_main', 'elec_resistance_sec'
    ]
    return param_order.index(param_name)


def _create_combo_from_baseline(baseline_dict, baseline_for_missing):
    """
    Create a full parameter tuple from baseline configuration.
    
    Parameters:
    -----------
    baseline_dict : dict
        Primary baseline configuration (determines scenario)
    baseline_for_missing : dict
        Fallback baseline for parameters not in primary
    
    Returns:
    --------
    tuple : Full parameter combination
    """
    return (
        baseline_dict['neighborhood'],
        baseline_dict['year'],
        baseline_dict['scenario'],
        baseline_dict['topology_source'],
        baseline_dict['spacing_m'],
        baseline_dict.get('heat_pump_cop', baseline_for_missing['heat_pump_cop']),
        baseline_dict.get('heat_substation_eff', HEAT_SUBSTATION_EFF[0]),
        baseline_dict.get('delta_t', DELTA_T[0]),
        baseline_dict.get('flow_speed', FLOW_SPEED[0]),
        baseline_dict.get('distance_factor_heat_trans_main', DISTANCE_FACTOR_HEAT_TRANS_MAIN[0]),
        baseline_dict.get('distance_factor_heat_dist_main', DISTANCE_FACTOR_HEAT_DIST_MAIN[0]),
        baseline_dict.get('distance_factor_heat_dist_sec', DISTANCE_FACTOR_HEAT_DIST_SEC[0]),
        baseline_for_missing.get('distance_factor_elec_dist_main', DISTANCE_FACTOR_ELEC_DIST_MAIN[0]),
        baseline_for_missing.get('distance_factor_elec_dist_sec', DISTANCE_FACTOR_ELEC_DIST_SEC[0]),
        baseline_dict.get('apply_heat_losses', APPLY_HEAT_LOSSES[0]),
        baseline_for_missing.get('apply_electricity_losses', APPLY_ELECTRICITY_LOSSES[0]),
        baseline_dict.get('heat_loss_rate_trans_main', HEAT_LOSS_RATE_TRANS_MAIN[0]),
        baseline_dict.get('heat_loss_rate_dist_main', HEAT_LOSS_RATE_DIST_MAIN[0]),
        baseline_dict.get('heat_loss_rate_dist_sec', HEAT_LOSS_RATE_DIST_SEC[0]),
        baseline_for_missing.get('elec_resistance_main', ELEC_RESISTANCE_MAIN[0]),
        baseline_for_missing.get('elec_resistance_sec', ELEC_RESISTANCE_SEC[0]),
    )


def generate_sensitivity_combinations():
    """
    Generate combinations for partial sensitivity study. 

    Each parameter is varied individually while others stay at baseline.
    
    District heating parameters use BASELINE_DH as base (multatulibuurt 2019 stedin DH)
    
    Electrification parameters use BASELINE_ELEC as base (multatulibuurt 2019 stedin elec)
    
    Returns:
    --------
    list : List of parameter combination tuples
    """
    combinations = []
    
    # Define which parameters belong to which scenario
    dh_params = {
        'spacing_m': SPACING_M,
        'heat_substation_eff': HEAT_SUBSTATION_EFF,
        'delta_t': DELTA_T,
        'flow_speed': FLOW_SPEED,
        'distance_factor_heat_trans_main': DISTANCE_FACTOR_HEAT_TRANS_MAIN,
        'distance_factor_heat_dist_main': DISTANCE_FACTOR_HEAT_DIST_MAIN,
        'distance_factor_heat_dist_sec': DISTANCE_FACTOR_HEAT_DIST_SEC,
        'heat_loss_rate_trans_main': HEAT_LOSS_RATE_TRANS_MAIN,
        'heat_loss_rate_dist_main': HEAT_LOSS_RATE_DIST_MAIN,
        'heat_loss_rate_dist_sec': HEAT_LOSS_RATE_DIST_SEC,
    }
    
    elec_params = {
        'spacing_m': SPACING_M,
        'heat_pump_cop': HEAT_PUMP_COP,
        'distance_factor_elec_dist_main': DISTANCE_FACTOR_ELEC_DIST_MAIN,
        'distance_factor_elec_dist_sec': DISTANCE_FACTOR_ELEC_DIST_SEC,
        'elec_resistance_main': ELEC_RESISTANCE_MAIN,
        'elec_resistance_sec': ELEC_RESISTANCE_SEC,
    }
    
    # Baseline district heating run
    baseline_dh_combo = _create_combo_from_baseline(BASELINE_DH, BASELINE_ELEC)
    combinations.append(baseline_dh_combo)
    
    # Baseline electrification run
    baseline_elec_combo = _create_combo_from_baseline(BASELINE_ELEC, BASELINE_ELEC)
    combinations.append(baseline_elec_combo)
    
    dh_variations = 0
    elec_variations = 0
    
    # District heating parameter sensitivities
    for param_name, param_values in dh_params.items():
        baseline_value = BASELINE_DH.get(param_name, param_values[0])
        for value in param_values:
            if value != baseline_value:  # Skip baseline value
                combo = list(_create_combo_from_baseline(BASELINE_DH, BASELINE_ELEC))
                param_idx = _get_param_index(param_name)
                combo[param_idx] = value
                combinations.append(tuple(combo))
                dh_variations += 1
    
    # Electrification parameter sensitivities
    for param_name, param_values in elec_params.items():
        baseline_value = BASELINE_ELEC.get(param_name, param_values[0])
        for value in param_values:
            if value != baseline_value:  # Skip baseline value
                combo = list(_create_combo_from_baseline(BASELINE_ELEC, BASELINE_ELEC))
                param_idx = _get_param_index(param_name)
                combo[param_idx] = value
                combinations.append(tuple(combo))
                elec_variations += 1
    
    # Print summary
    print(f"\nSensitivity study configuration:")
    print(f"  Total combinations: {len(combinations)}")
    print(f"  - 2 baseline runs (DH + Elec)")
    print(f"  - {dh_variations} district heating parameter variations")
    print(f"  - {elec_variations} electrification parameter variations")
    
    return combinations


# =============================================================================
# Execution functions: single scenario run, aggregation of results
# =============================================================================

def run_single_scenario(neighborhood, year, scenario, topology_source,
                       spacing_m, heat_pump_cop, heat_substation_eff,
                       delta_t, flow_speed,
                       distance_factor_heat_trans_main,
                       distance_factor_heat_dist_main,
                       distance_factor_heat_dist_sec,
                       distance_factor_elec_dist_main,
                       distance_factor_elec_dist_sec,
                       apply_heat_losses,
                       apply_electricity_losses,
                       heat_loss_rate_trans_main,
                       heat_loss_rate_dist_main,
                       heat_loss_rate_dist_sec,
                       elec_resistance_main,
                       elec_resistance_sec):
    """
    Run a single scenario by invoking run_analysis.py as a subprocess.
    
    Creates output directories, saves parameters to JSON, executes the
    analysis script, and captures all outputs. Includes a random delay
    at start to reduce I/O contention when running in parallel.
    
    Parameters
    ----------
    neighborhood : str
        Neighborhood name (e.g., 'multatulibuurt')
    year : int
        Demand year for the scenario (e.g., 2019)
    scenario : str
        Heating scenario type ('district_heating', 'full_electrification', 'hybrid')
    topology_source : str
        Network topology source ('stedin' or 'osm')
    spacing_m : float
        Node spacing in meters for network discretization
    heat_pump_cop : float
        Coefficient of performance for heat pumps
    heat_substation_eff : float
        Heat substation efficiency (0-1)
    delta_t : float
        Temperature difference for pipe sizing (degrees C)
    flow_speed : float
        Flow speed for pipe sizing (m/s)
    distance_factor_heat_trans_main : float
        Distance multiplier for heat transmission main pipes
    distance_factor_heat_dist_main : float
        Distance multiplier for heat distribution main pipes
    distance_factor_heat_dist_sec : float
        Distance multiplier for heat distribution secondary pipes
    distance_factor_elec_dist_main : float
        Distance multiplier for electricity distribution main cables
    distance_factor_elec_dist_sec : float
        Distance multiplier for electricity distribution secondary cables
    apply_heat_losses : bool
        Whether to apply heat transmission losses
    apply_electricity_losses : bool
        Whether to apply electricity transmission losses
    heat_loss_rate_trans_main : float
        Heat loss rate for transmission main (W/m)
    heat_loss_rate_dist_main : float
        Heat loss rate for distribution main (W/m)
    heat_loss_rate_dist_sec : float
        Heat loss rate for distribution secondary (W/m)
    elec_resistance_main : float
        Electrical resistance for main cables (Ohm/km)
    elec_resistance_sec : float
        Electrical resistance for secondary cables (Ohm/km)
    
    Returns
    -------
    dict
        Results dictionary containing:
        - run_id: Unique identifier for this run
        - success: Boolean indicating if run completed successfully
        - duration_seconds: Execution time
        - returncode: Subprocess return code
        - output_dir: Path to output directory
        - timestamp: ISO format start timestamp
        - error: Error message (only if failed)
        - All input parameters
    """
    
    time.sleep(random.uniform(0, 1))  # Stagger start times to reduce I/O contention

    # Create parameter dictionary for tracking
    params = {
        'neighborhood': neighborhood,
        'year': year,
        'scenario': scenario,
        'topology_source': topology_source,
        'spacing_m': spacing_m,
        'heat_pump_cop': heat_pump_cop,
        'heat_substation_eff': heat_substation_eff,
        'delta_t': delta_t,
        'flow_speed': flow_speed,
        'distance_factor_heat_trans_main': distance_factor_heat_trans_main,
        'distance_factor_heat_dist_main': distance_factor_heat_dist_main,
        'distance_factor_heat_dist_sec': distance_factor_heat_dist_sec,
        'distance_factor_elec_dist_main': distance_factor_elec_dist_main,
        'distance_factor_elec_dist_sec': distance_factor_elec_dist_sec,
        'apply_heat_losses': apply_heat_losses,
        'apply_electricity_losses': apply_electricity_losses,
        'heat_loss_rate_trans_main': heat_loss_rate_trans_main,
        'heat_loss_rate_dist_main': heat_loss_rate_dist_main,
        'heat_loss_rate_dist_sec': heat_loss_rate_dist_sec,
        'elec_resistance_main': elec_resistance_main,
        'elec_resistance_sec': elec_resistance_sec,
        'apply_heat_losses': apply_heat_losses,
        'apply_electricity_losses': apply_electricity_losses,
    }
    
    # Generate hash from parameters for unique identification
    param_str = json.dumps(params, sort_keys=True)
    param_hash = hashlib.md5(param_str.encode()).hexdigest()[:8]
    
    # Create unique identifier with hash
    run_id = f"{neighborhood}_{year}_{scenario}_{topology_source}_{param_hash}"
    
    # Create output directory structure for this specific run
    output_dir = os.path.join(RESULTS_BASE_DIR, TIMESTAMP, run_id)
    data_tables_dir = os.path.join(output_dir, 'data_tables')
    outputs_dir = os.path.join(output_dir, 'outputs')
    debug_dir = os.path.join(output_dir, 'debug')
    os.makedirs(data_tables_dir, exist_ok=True)
    os.makedirs(outputs_dir, exist_ok=True)
    os.makedirs(debug_dir, exist_ok=True)
    
    # Save full parameters to JSON for reference
    params_file = os.path.join(output_dir, 'parameters.json')
    with open(params_file, 'w') as f:
        json.dump(params, f, indent=2)

    # Build command with all parameters
    cmd = [
        'python',
        'run_analysis.py',
        '--neighborhood', neighborhood,
        '--year', str(year),
        '--scenario', scenario,
        '--topology_source', topology_source,
        '--mode', MODE,
        '--data-tables-folder', data_tables_dir,
        '--output-folder', outputs_dir,
        '--debug-folder', debug_dir,
        '--spacing', str(spacing_m),
        '--heat-pump-cop', str(heat_pump_cop),
        '--heat-substation-eff', str(heat_substation_eff),
        '--delta-t', str(delta_t),
        '--flow-speed', str(flow_speed),
        '--distance-factor-heat-trans-main', str(distance_factor_heat_trans_main),
        '--distance-factor-heat-dist-main', str(distance_factor_heat_dist_main),
        '--distance-factor-heat-dist-sec', str(distance_factor_heat_dist_sec),
        '--distance-factor-elec-dist-main', str(distance_factor_elec_dist_main),
        '--distance-factor-elec-dist-sec', str(distance_factor_elec_dist_sec),
        '--heat-loss-rate-trans-main', str(heat_loss_rate_trans_main),
        '--heat-loss-rate-dist-main', str(heat_loss_rate_dist_main),
        '--heat-loss-rate-dist-sec', str(heat_loss_rate_dist_sec),
        '--elec-resistance-main', str(elec_resistance_main),
        '--elec-resistance-sec', str(elec_resistance_sec),
        '--apply-heat-losses', str(apply_heat_losses).lower(),
        '--apply-electricity-losses', str(apply_electricity_losses).lower(),
    ]
    
    print(f"Starting: {run_id}")
    start_time = datetime.now()
    
    try:
        env = os.environ.copy()
        
        # Run the analysis
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=os.getcwd(),
            timeout=TIMEOUT_SECONDS,
            env=env  # Pass modified environment
        )
        
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        
        # Save outputs
        with open(os.path.join(output_dir, 'stdout.txt'), 'w') as f:
            f.write(result.stdout)
        
        with open(os.path.join(output_dir, 'stderr.txt'), 'w') as f:
            f.write(result.stderr)

        
        # Determine success
        success = result.returncode == 0
        
        result_dict = {
            'run_id': run_id,
            'success': success,
            'duration_seconds': duration,
            'returncode': result.returncode,
            'output_dir': output_dir,
            'timestamp': start_time.isoformat()
        }
        result_dict.update(params)  # Add all parameters
        return result_dict
        
    except subprocess.TimeoutExpired:
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        print(f"TIMEOUT: {run_id} (exceeded {TIMEOUT_SECONDS}s)")
        
        result_dict = {
            'run_id': run_id,
            'success': False,
            'duration_seconds': duration,
            'returncode': -1,
            'error': 'Timeout exceeded',
            'output_dir': output_dir,
            'timestamp': start_time.isoformat()
        }
        result_dict.update(params)  # Add all parameters
        return result_dict
        
    except Exception as e:
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        print(f"ERROR: {run_id} - {str(e)}")
        
        result_dict = {
            'run_id': run_id,
            'success': False,
            'duration_seconds': duration,
            'returncode': -1,
            'error': str(e),
            'output_dir': output_dir,
            'timestamp': start_time.isoformat()
        }
        result_dict.update(params)  # Add all parameters
        return result_dict

def aggregate_scenario_summaries(results_list, timestamp):
    """
    Aggregate individual scenario summaries into a master summary
    
    Automatically flattens nested JSON structures so changes to summary
    format don't break aggregation.
    
    Parameters:
    -----------
    results_list : list
        List of result dictionaries from parallel runs
    timestamp : str
        Timestamp for this batch run
    
    Returns:
    --------
    pd.DataFrame : Aggregated summary table
    """
    summaries = []
    
    for result in results_list:
        # Load the scenario summary JSON if it exists
        summary_path = os.path.join(result['output_dir'], 'outputs', 'scenario_summary.json')
        
        # Start with basic run metadata
        summary_row = {
            'run_id': result['run_id'],
            'neighborhood': result['neighborhood'],
            'year': result['year'],
            'scenario': result['scenario'],
            'topology_source': result['topology_source'],
            'success': result['success'],
            'duration_seconds': result['duration_seconds'],
        }
        
        if os.path.exists(summary_path):
            try:
                with open(summary_path, 'r') as f:
                    scenario_summary = json.load(f)
                
                # Recursively flatten the entire JSON structure
                flattened = _flatten_dict(scenario_summary)
                
                # Add all flattened fields to the summary row
                summary_row.update(flattened)
                
            except Exception as e:
                summary_row['summary_load_error'] = str(e)
        else:
            summary_row['summary_exists'] = False
        
        summaries.append(summary_row)
    
    return pd.DataFrame(summaries)


def _flatten_dict(d, parent_key='', sep='_'):
    """
    Recursively flatten a nested dictionary
    
    Parameters:
    -----------
    d : dict
        Dictionary to flatten
    parent_key : str
        Prefix for keys (used in recursion)
    sep : str
        Separator between nested keys
    
    Returns:
    --------
    dict : Flattened dictionary
    
    Examples:
    ---------
    >>> _flatten_dict({'a': {'b': 1, 'c': 2}})
    {'a_b': 1, 'a_c': 2}
    """
    items = []
    for k, v in d.items():
        new_key = f"{parent_key}{sep}{k}" if parent_key else k
        
        if isinstance(v, dict):
            # Recursively flatten nested dicts
            items.extend(_flatten_dict(v, new_key, sep=sep).items())
        elif isinstance(v, list):
            # Convert lists to comma-separated strings or skip if complex
            if v and isinstance(v[0], (dict, list)):
                # Skip complex nested structures
                items.append((new_key, str(v)))
            else:
                items.append((new_key, ', '.join(map(str, v))))
        else:
            # Regular value
            items.append((new_key, v))
    
    return dict(items)

def run_parallel_scenarios():
    """
    Execute all scenario combinations in parallel using ProcessPoolExecutor.
    
    Generates sensitivity study combinations, displays configuration summary,
    creates output directories, and runs all scenarios using parallel workers.
    Progress is printed as each scenario completes.
    
    Returns
    -------
    list of dict
        List of result dictionaries from each scenario run, as returned
        by run_single_scenario()
    """
    # Generate sensitivity study combinations (one parameter at a time)
    print("Generating sensitivity study combinations...")
    combinations = generate_sensitivity_combinations()
    
    total_runs = len(combinations)
    print(f"\n{'='*80}")
    print(f"PARALLEL SCENARIO EXECUTION")
    print(f"{'='*80}")
    print(f"Total combinations: {total_runs}")
    print(f"Max parallel workers: {MAX_WORKERS}")
    print(f"\nParameter Ranges:")
    print(f"  Neighborhoods ({len(NEIGHBORHOODS)}): {NEIGHBORHOODS}")
    print(f"  Years ({len(YEARS)}): {YEARS}")
    print(f"  Scenarios ({len(SCENARIOS)}): {SCENARIOS}")
    print(f"  Topology sources ({len(TOPOLOGY_SOURCES)}): {TOPOLOGY_SOURCES}")
    print(f"  Spacing (m) ({len(SPACING_M)}): {SPACING_M}")
    print(f"  Heat pump COP ({len(HEAT_PUMP_COP)}): {HEAT_PUMP_COP}")
    print(f"  Heat substation eff ({len(HEAT_SUBSTATION_EFF)}): {HEAT_SUBSTATION_EFF}")
    print(f"  Delta T (°C) ({len(DELTA_T)}): {DELTA_T}")
    print(f"  Flow speed (m/s) ({len(FLOW_SPEED)}): {FLOW_SPEED}")
    print(f"  Distance factors: {len(DISTANCE_FACTOR_HEAT_TRANS_MAIN) * len(DISTANCE_FACTOR_HEAT_DIST_MAIN) * len(DISTANCE_FACTOR_HEAT_DIST_SEC) * len(DISTANCE_FACTOR_ELEC_DIST_MAIN) * len(DISTANCE_FACTOR_ELEC_DIST_SEC)} combinations")
    print(f"  Heat loss rates: {len(HEAT_LOSS_RATE_TRANS_MAIN) * len(HEAT_LOSS_RATE_DIST_MAIN) * len(HEAT_LOSS_RATE_DIST_SEC)} combinations")
    print(f"  Elec resistance: {len(ELEC_RESISTANCE_MAIN) * len(ELEC_RESISTANCE_SEC)} combinations")
    print(f"\nResults directory: {os.path.join(RESULTS_BASE_DIR, TIMESTAMP)}")
    print(f"{'='*80}\n")
    
    # Create base results directory
    os.makedirs(os.path.join(RESULTS_BASE_DIR, TIMESTAMP), exist_ok=True)
    
    # Execute in parallel
    results = []
    completed = 0
    
    with ProcessPoolExecutor(max_workers=MAX_WORKERS) as executor:
        # Submit all jobs
        future_to_params = {
            executor.submit(run_single_scenario, *combo): combo 
            for combo in combinations
        }
        
        # Collect results as they complete
        for future in as_completed(future_to_params):
            result = future.result()
            results.append(result)
            completed += 1
            
            status = "SUCCESS" if result['success'] else "FAILED"
            print(f"[{completed}/{total_runs}] {status}: {result['run_id']} ({result['duration_seconds']:.1f}s)")
    
    return results


def save_results_summary(results):
    """
    Save comprehensive results summary and print execution statistics.
    
    Saves results to CSV and JSON formats, aggregates scenario summaries,
    and prints detailed statistics including success rates by category.
    
    Parameters
    ----------
    results : list of dict
        List of result dictionaries from run_parallel_scenarios()
    
    Side Effects
    ------------
    - Creates execution_summary.csv in results directory
    - Creates execution_summary.json in results directory  
    - Creates scenario_summary.csv with aggregated scenario data
    - Prints execution statistics to stdout
    """
    # Convert to DataFrame
    df = pd.DataFrame(results)
    
    # Save execution summary to CSV
    summary_file = os.path.join(RESULTS_BASE_DIR, TIMESTAMP, 'execution_summary.csv')
    df.to_csv(summary_file, index=False)
    
    # Save to JSON
    json_file = os.path.join(RESULTS_BASE_DIR, TIMESTAMP, 'execution_summary.json')
    with open(json_file, 'w') as f:
        json.dump(results, f, indent=2)
    
    # Create aggregated scenario summaries
    print("\nAggregating scenario summaries...")
    aggregated_summary = aggregate_scenario_summaries(results, TIMESTAMP)
    scenarios_file = os.path.join(RESULTS_BASE_DIR, TIMESTAMP, 'scenario_summary.csv')
    aggregated_summary.to_csv(scenarios_file, index=False)
    
    # Print summary statistics
    print(f"\n{'='*80}")
    print(f"EXECUTION SUMMARY")
    print(f"{'='*80}")
    print(f"Total runs: {len(results)}")
    print(f"Successful: {sum(r['success'] for r in results)}")
    print(f"Failed: {sum(not r['success'] for r in results)}")
    print(f"Total CPU time: {sum(r['duration_seconds'] for r in results):.1f}s")
    print(f"Average time per run: {sum(r['duration_seconds'] for r in results) / len(results):.1f}s")
    print(f"\nResults saved to:")
    print(f"  - {summary_file}")
    print(f"  - {json_file}")
    print(f"  - {scenarios_file}")
    print(f"{'='*80}\n")
    
    # Print failures if any
    failures = [r for r in results if not r['success']]
    if failures:
        print(f"\n{'='*80}")
        print(f"FAILED RUNS ({len(failures)})")
        print(f"{'='*80}")
        for fail in failures:
            print(f"  {fail['run_id']}")
            if 'error' in fail:
                print(f"    Error: {fail['error']}")
        print(f"{'='*80}\n")
    
    # Summary by category
    print(f"\n{'='*80}")
    print(f"SUCCESS RATE BY CATEGORY")
    print(f"{'='*80}")
    
    # Show stats for categories with multiple values
    categories = ['neighborhood', 'year', 'scenario', 'topology_source', 
                  'spacing_m', 'heat_pump_cop', 'heat_substation_eff', 
                  'delta_t', 'flow_speed']
    
    for category in categories:
        if category in df.columns and len(df[category].unique()) > 1:
            print(f"\n{category.upper()}:")
            category_stats = df.groupby(category)['success'].agg(['sum', 'count'])
            category_stats['rate'] = (category_stats['sum'] / category_stats['count'] * 100).round(1)
            for idx, row in category_stats.iterrows():
                print(f"  {idx}: {row['sum']}/{row['count']} ({row['rate']}%)")
    
    print(f"{'='*80}\n")

# =============================================================================
# Main execution
# =============================================================================

if __name__ == "__main__":
    import sys
    
    # Parse command line arguments
    parser = argparse.ArgumentParser(
        description='Run parallel scenario execution for energy system analysis'
    )
    parser.add_argument(
        '--config', '-c',
        default='run_parallel_config.yaml',
        help='Path to YAML configuration file (default: run_parallel_config.yaml)'
    )
    args = parser.parse_args()
    
    # Change to delft_calliope directory
    if not os.path.exists('run_analysis.py'):
        print("ERROR: Must run from delft_calliope directory")
        sys.exit(1)
    
    # Check config file exists
    if not os.path.exists(args.config):
        print(f"ERROR: Configuration file not found: {args.config}")
        sys.exit(1)
    
    # Initialize configuration from YAML
    print(f"Loading configuration from: {args.config}")
    init_config(args.config)
    
    # Generate combinations to get accurate count
    test_combinations = generate_sensitivity_combinations()
    
    # Show configuration
    print("\n" + "="*80)
    print("PARALLEL EXECUTION CONFIGURATION - SENSITIVITY STUDY")
    print("="*80)
    print(f"Configuration file: {args.config}")
    print(f"Parallel workers: {MAX_WORKERS}")
    print(f"\nSensitivity study setup:")
    print(f"  Baseline scenarios: 2 (DH + Elec)")
    print(f"  Parameter variations: {len(test_combinations) - 2}")
    print(f"  Total runs: {len(test_combinations)}")
    print(f"\nBaseline configuration:")
    print(f"  Neighborhood: {BASELINE_DH['neighborhood']}")
    print(f"  Year: {BASELINE_DH['year']}")
    print(f"  Topology: {BASELINE_DH['topology_source']}")
    print("="*80)
    
    response = input("\nProceed? (yes/no): ")
    if response.lower() not in ['yes', 'y']:
        print("Execution cancelled.")
        sys.exit(0)
    
    # Run parallel execution
    start_time = datetime.now()
    results = run_parallel_scenarios()
    end_time = datetime.now()
    
    # Save results
    save_results_summary(results)
    
    wall_time = (end_time - start_time).total_seconds()
    cpu_time = sum(r['duration_seconds'] for r in results)
    print(f"\nTotal wall clock time: {wall_time:.1f}s ({wall_time/60:.1f} minutes)")
    print(f"Total CPU time: {cpu_time:.1f}s ({cpu_time/60:.1f} minutes)")
    print(f"Speedup factor: {cpu_time / wall_time:.1f}x")
    print(f"Core utilization efficiency: {(cpu_time / wall_time) / MAX_WORKERS * 100:.1f}%\n")