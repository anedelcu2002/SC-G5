"""
Parallel Scenario Execution Script - Optimized for 16-core CPU
Run multiple scenario combinations in parallel for comprehensive analysis
"""

import os
import subprocess
import itertools
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
import pandas as pd
import json
import time
import random

# =============================================================================
# CONFIGURATION
# =============================================================================

# Define all parameter combinations to run
NEIGHBORHOODS = [
#                 'multatulibuurt', 
                 'holstbuurt', 
#                 'mythologiebuurt',
#                 'poptahofzuid'
                 ]
YEARS = [
         2013, 
#         2019, 
#         2020
         ]
SCENARIOS = [
#             'district_heating', 
             'full_electrification', 
#             'hybrid'
             ]
TOPOLOGY_SOURCES = [
#                    'stedin', 
                    'osm'
                    ]
SPACING_M = [5.0]  # Node spacing in meters

# District heating parameters
HEAT_PUMP_COP = [
#                 3, 
                 4.0, 
#                 5.5
                 ]  # Heat pump coefficient of performance
HEAT_SUBSTATION_EFF = [
#                       0.81, 
                       0.9, 
#                       0.99
                       ]  # Heat substation efficiency
DELTA_T = [25]  # Temperature difference for pipe sizing (°C)
FLOW_SPEED = [
#            0.56, 
            0.62, 
#            0.68
            ]  # Flow speed for pipe sizing (m/s)
DISTANCE_FACTOR_HEAT_TRANS_MAIN = [1.0] # no variation expected
DISTANCE_FACTOR_HEAT_DIST_MAIN = [
#    0.9, 
    1.0, 
#    1.1
    ] # 10% variation
DISTANCE_FACTOR_HEAT_DIST_SEC = [
#    0.9, 
    1.0, 
#    1.1
    ] # 10% variation
HEAT_LOSS_RATE_TRANS_MAIN = [
#    59.2, 
    65.8, 
#    72.4
    ] # 10% variation
HEAT_LOSS_RATE_DIST_MAIN = [
#    46.8, 
    52, 
#    57.2
    ]
HEAT_LOSS_RATE_DIST_SEC = [
#    26.1, 
    29, 
#    31.9
    ]

# Heat pump parameters
DISTANCE_FACTOR_ELEC_DIST_MAIN = [
#    0.9, 
    1.0, 
#    1.1
    ]
DISTANCE_FACTOR_ELEC_DIST_SEC = [
#    0.9, 
    1.0, 
#    1.1
    ]
ELEC_RESISTANCE_MAIN = [
#    0.222, 
    0.247, 
#    0.272
    ]
ELEC_RESISTANCE_SEC = [
#    0.222, 
    0.247, 
#    0.272
    ]

# Loss calculation enable/disable
APPLY_HEAT_LOSSES = [True]  # Set to [True, False] to test both
APPLY_ELECTRICITY_LOSSES = [True]  # Set to [True, False] to test both

# Parallel execution settings
MAX_WORKERS = 1  # Number of parallel scenario runs
GUROBI_THREADS = 0  # Threads per Gurobi solve (16 cores / 4 workers = 4 threads each)

MODE = 'plot'  # Use 'export' to skip visualizations for faster execution

# Output organization
RESULTS_BASE_DIR = 'parallel_results'
TIMESTAMP = datetime.now().strftime('%Y%m%d_%H%M%S')


# =============================================================================
# PARAMETER CONSTRAINTS
# =============================================================================

def generate_valid_combinations():
    """
    Generator that yields only valid parameter combinations based on scenario type.
    
    Constraints:
    - district_heating: Only uses first value of heat pump parameters (no variation)
    - full_electrification: Only uses first value of district heating parameters (no variation)
    - hybrid: Can vary both parameter sets
    
    This avoids materializing invalid combinations in memory.
    
    Yields:
    -------
    tuple : Valid parameter combination
    """
    total_generated = 0
    total_valid = 0
    
    for combo in itertools.product(
        NEIGHBORHOODS, YEARS, SCENARIOS, TOPOLOGY_SOURCES,
        SPACING_M, HEAT_PUMP_COP, HEAT_SUBSTATION_EFF,
        DELTA_T, FLOW_SPEED,
        DISTANCE_FACTOR_HEAT_TRANS_MAIN, DISTANCE_FACTOR_HEAT_DIST_MAIN,
        DISTANCE_FACTOR_HEAT_DIST_SEC, DISTANCE_FACTOR_ELEC_DIST_MAIN,
        DISTANCE_FACTOR_ELEC_DIST_SEC,
        APPLY_HEAT_LOSSES, APPLY_ELECTRICITY_LOSSES,
        HEAT_LOSS_RATE_TRANS_MAIN, HEAT_LOSS_RATE_DIST_MAIN,
        HEAT_LOSS_RATE_DIST_SEC,
        ELEC_RESISTANCE_MAIN, ELEC_RESISTANCE_SEC
    ):
        total_generated += 1
        
        # Unpack combination
        (neighborhood, year, scenario, topology_source,
         spacing_m, heat_pump_cop, heat_substation_eff,
         delta_t, flow_speed,
         distance_factor_heat_trans_main, distance_factor_heat_dist_main,
         distance_factor_heat_dist_sec, distance_factor_elec_dist_main,
         distance_factor_elec_dist_sec,
         apply_heat_losses, apply_electricity_losses,
         heat_loss_rate_trans_main, heat_loss_rate_dist_main,
         heat_loss_rate_dist_sec,
         elec_resistance_main, elec_resistance_sec) = combo
        
        # Apply scenario-specific constraints
        if scenario == 'district_heating':
            # District heating doesn't use heat pumps - skip if heat pump params are varied
            if (distance_factor_elec_dist_main != DISTANCE_FACTOR_ELEC_DIST_MAIN[0] or
                distance_factor_elec_dist_sec != DISTANCE_FACTOR_ELEC_DIST_SEC[0] or
                elec_resistance_main != ELEC_RESISTANCE_MAIN[0] or
                elec_resistance_sec != ELEC_RESISTANCE_SEC[0]):
                continue
        
        elif scenario == 'full_electrification':
            # Full electrification doesn't use district heating - skip if district heating params are varied
            if (heat_pump_cop != HEAT_PUMP_COP[0] or
                heat_substation_eff != HEAT_SUBSTATION_EFF[0] or
                delta_t != DELTA_T[0] or
                flow_speed != FLOW_SPEED[0] or
                distance_factor_heat_trans_main != DISTANCE_FACTOR_HEAT_TRANS_MAIN[0] or
                distance_factor_heat_dist_main != DISTANCE_FACTOR_HEAT_DIST_MAIN[0] or
                distance_factor_heat_dist_sec != DISTANCE_FACTOR_HEAT_DIST_SEC[0] or
                heat_loss_rate_trans_main != HEAT_LOSS_RATE_TRANS_MAIN[0] or
                heat_loss_rate_dist_main != HEAT_LOSS_RATE_DIST_MAIN[0] or
                heat_loss_rate_dist_sec != HEAT_LOSS_RATE_DIST_SEC[0]):
                continue
        
        # hybrid scenario can vary all parameters - no constraints
        
        total_valid += 1
        yield combo
    
    # Print filtering statistics
    if total_generated > total_valid:
        filtered_out = total_generated - total_valid
        pct_filtered = (filtered_out / total_generated * 100)
        print(f"Constraint filtering: {filtered_out:,} combinations filtered out ({pct_filtered:.1f}%)")
        print(f"Valid combinations: {total_valid:,} / {total_generated:,}\n")


# =============================================================================
# EXECUTION FUNCTIONS
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
    Run a single scenario combination
    
    Returns:
    --------
    dict : Results with status, timing, and output information
    """
    import hashlib
    
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
        # Set environment variable to limit Gurobi threads for this process
        env = os.environ.copy()
        env['GRB_THREADS'] = str(GUROBI_THREADS)
        
        # Run the analysis
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=os.getcwd(),
            timeout=3600,  # 1 hour timeout
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
        print(f"TIMEOUT: {run_id} (exceeded 1 hour)")
        
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
    Execute all scenario combinations in parallel
    """
    # Generate valid combinations efficiently (filters during generation)
    print("Generating valid parameter combinations...")
    combinations = list(generate_valid_combinations())
    
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
            
            status = "✓ SUCCESS" if result['success'] else "✗ FAILED"
            print(f"[{completed}/{total_runs}] {status}: {result['run_id']} ({result['duration_seconds']:.1f}s)")
    
    return results


def save_results_summary(results):
    """
    Save comprehensive results summary
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
    
    # NEW: Create aggregated scenario summaries
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
    print(f"  - {scenarios_file}")  # NEW
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
# MAIN EXECUTION
# =============================================================================

if __name__ == "__main__":
    import sys
    
    # Change to delft_calliope directory
    if not os.path.exists('run_analysis.py'):
        print("ERROR: Must run from delft_calliope directory")
        sys.exit(1)
    
    # Show configuration
    print("\n" + "="*80)
    print("PARALLEL EXECUTION CONFIGURATION")
    print("="*80)
    print(f"CPU Cores: 16 (detected)")
    print(f"Parallel workers: {MAX_WORKERS}")
    print(f"Gurobi threads per worker: {GUROBI_THREADS}")
    print(f"Total utilization: {MAX_WORKERS * GUROBI_THREADS} cores")
    print(f"\nScenario combinations:")
    print(f"  Neighborhoods: {len(NEIGHBORHOODS)}")
    print(f"  Years: {len(YEARS)}")
    print(f"  Scenarios: {len(SCENARIOS)}")
    print(f"  Topology sources: {len(TOPOLOGY_SOURCES)}")
    print(f"  Total: {len(NEIGHBORHOODS) * len(YEARS) * len(SCENARIOS) * len(TOPOLOGY_SOURCES)} runs")
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
    print(f"Core utilization efficiency: {(cpu_time / wall_time) / 16 * 100:.1f}%\n")