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
#                 'holstbuurt', 
#                 'mythologiebuurt',
                 'poptahofzuid'
                 ]
YEARS = [
         2013, 
         2019, 
         2020
         ]
SCENARIOS = [
             'district_heating', 
             'full_electrification', 
#             'hybrid'
             ]
TOPOLOGY_SOURCES = [
                    'stedin', 
                    'osm'
                    ]

# Execution settings - OPTIMIZED FOR 16 CORES
# Strategy: Run 4 scenarios in parallel, each using 4 Gurobi threads
# Total: 4 processes × 4 threads = 16 cores fully utilized
MAX_WORKERS = 2  # Number of parallel scenario runs
GUROBI_THREADS = 0  # Threads per Gurobi solve (16 cores / 4 workers = 4 threads each)

MODE = 'plot'  # Use 'export' to skip visualizations for faster execution

# Output organization
RESULTS_BASE_DIR = 'parallel_results'
TIMESTAMP = datetime.now().strftime('%Y%m%d_%H%M%S')


# =============================================================================
# EXECUTION FUNCTIONS
# =============================================================================

def run_single_scenario(neighborhood, year, scenario, topology_source):
    """
    Run a single scenario combination
    
    Returns:
    --------
    dict : Results with status, timing, and output information
    """
    time.sleep(random.uniform(0, 5))  # Stagger start times to reduce I/O contention

    # Create unique identifier for this run
    run_id = f"{neighborhood}_{year}_{scenario}_{topology_source}"
    
    # Create output directory structure for this specific run
    output_dir = os.path.join(RESULTS_BASE_DIR, TIMESTAMP, run_id)
    data_tables_dir = os.path.join(output_dir, 'data_tables')
    outputs_dir = os.path.join(output_dir, 'outputs')
    os.makedirs(data_tables_dir, exist_ok=True)
    os.makedirs(outputs_dir, exist_ok=True)

    # Build command - IMPORTANT: Pass isolated folders
    cmd = [
        'python',
        'run_analysis.py',
        '--neighborhood', neighborhood,
        '--year', str(year),
        '--scenario', scenario,
        '--topology_source', topology_source,
        '--mode', MODE,
        '--data-tables-folder', data_tables_dir,  # NEW: Isolated data tables
        '--output-folder', outputs_dir              # Updated: outputs subfolder
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
        
        return {
            'run_id': run_id,
            'neighborhood': neighborhood,
            'year': year,
            'scenario': scenario,
            'topology_source': topology_source,
            'success': success,
            'duration_seconds': duration,
            'returncode': result.returncode,
            'output_dir': output_dir,
            'timestamp': start_time.isoformat()
        }
        
    except subprocess.TimeoutExpired:
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        print(f"TIMEOUT: {run_id} (exceeded 1 hour)")
        
        return {
            'run_id': run_id,
            'neighborhood': neighborhood,
            'year': year,
            'scenario': scenario,
            'topology_source': topology_source,
            'success': False,
            'duration_seconds': duration,
            'returncode': -1,
            'error': 'Timeout exceeded',
            'output_dir': output_dir,
            'timestamp': start_time.isoformat()
        }
        
    except Exception as e:
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        print(f"ERROR: {run_id} - {str(e)}")
        
        return {
            'run_id': run_id,
            'neighborhood': neighborhood,
            'year': year,
            'scenario': scenario,
            'topology_source': topology_source,
            'success': False,
            'duration_seconds': duration,
            'returncode': -1,
            'error': str(e),
            'output_dir': output_dir,
            'timestamp': start_time.isoformat()
        }

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
    # Generate all combinations
    combinations = list(itertools.product(
        NEIGHBORHOODS,
        YEARS,
        SCENARIOS,
        TOPOLOGY_SOURCES
    ))
    
    total_runs = len(combinations)
    print(f"\n{'='*80}")
    print(f"PARALLEL SCENARIO EXECUTION - OPTIMIZED FOR 16 CORES")
    print(f"{'='*80}")
    print(f"Total combinations: {total_runs}")
    print(f"Max parallel workers: {MAX_WORKERS}")
    print(f"Gurobi threads per worker: {GUROBI_THREADS}")
    print(f"Total core utilization: {MAX_WORKERS} × {GUROBI_THREADS} = {MAX_WORKERS * GUROBI_THREADS} cores")
    print(f"API thread pools: 4 threads per worker (I/O bound, minimal CPU impact)")
    print(f"\nNeighborhoods: {', '.join(NEIGHBORHOODS)}")
    print(f"Years: {', '.join(map(str, YEARS))}")
    print(f"Scenarios: {', '.join(SCENARIOS)}")
    print(f"Topology sources: {', '.join(TOPOLOGY_SOURCES)}")
    print(f"Results directory: {os.path.join(RESULTS_BASE_DIR, TIMESTAMP)}")
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
    scenarios_file = os.path.join(RESULTS_BASE_DIR, TIMESTAMP, 'scenarios_summary.csv')
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
    
    for category in ['neighborhood', 'year', 'scenario', 'topology_source']:
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