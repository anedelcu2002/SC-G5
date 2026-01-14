import json
import os
from datetime import datetime

def save_scenario_summary(config, model, results_df, output_folder, execution_times):
    """
    Save comprehensive scenario summary to JSON file
    
    Parameters:
    -----------
    config : dict
        Configuration dictionary
    model : calliope.Model
        Solved Calliope model
    results_df : pd.DataFrame
        Results dataframe from process_calliope_results
    output_folder : str
        Path to output folder
    execution_times : dict
        Dictionary of execution times
    """
    
    summary = {
        # Scenario identification
        'scenario_info': {
            'neighborhood': config['neighborhood'],
            'neighborhood_name': config.get('neighborhood_name', ''),
            'year': config['year'],
            'scenario_type': config['scenario'],
            'topology_source': config['topology_source'],
            'timestamp': datetime.now().isoformat(),
        },
        
        # Model configuration
        'model_config': {
            'node_spacing_m': config['spacing_m'],
            'debug_single_node': config['debug_single_node'],
            'online_mode': config['online'],
            'mode': config['mode'],
        },
        
        # Technology parameters
        'technology_parameters': config['tech_efficiencies'],
        
        # Network parameters
        'network_info': {
            'substation_coords': config.get('substation_coords', None),
            'bbox_coords': config.get('bbox_coords', None),
        },
        
        # Model size and complexity
        'model_size': {
            'num_nodes': int(len(model.inputs.coords.get('nodes', []))),
            'num_techs': int(len(model.inputs.coords.get('techs', []))),
            'num_carriers': int(len(model.inputs.coords.get('carriers', []))),
            'num_timesteps': int(len(model.inputs.coords.get('timesteps', []))),
        },
        
        # Solver information
        'solver_info': {
            'solver': model.config.solve.solver if hasattr(model.config.solve, 'solver') else 'unknown',
            'solver_status': model.results.attrs.get('termination_condition', 'unknown') if hasattr(model, 'results') else 'not_solved',
        },
        
        # Results summary
        'results_summary': {},
        
        # Execution times
        'execution_times': {
            'total_seconds': sum(execution_times.values()),
            'breakdown': execution_times
        }
    }
    
    # Add results summary if model was solved successfully
    if hasattr(model, 'results') and len(model.results.data_vars) > 0:
        try:
            # Total costs
            if 'cost' in model.results:
                total_cost = float(model.results['cost'].sum())
                summary['results_summary']['total_cost'] = total_cost
            
            # Capacity information
            if 'flow_cap' in model.results:
                flow_caps = model.results['flow_cap']
                summary['results_summary']['total_capacity_installed'] = float(flow_caps.sum())
                
                # Capacity by tech
                capacity_by_tech = {}
                for tech in flow_caps.coords.get('techs', []):
                    cap = float(flow_caps.sel(techs=tech).sum())
                    if cap > 0:
                        capacity_by_tech[str(tech.values)] = cap
                summary['results_summary']['capacity_by_technology'] = capacity_by_tech
            
            # Energy flows
            if 'flow_out' in model.results:
                flow_out = model.results['flow_out']
                summary['results_summary']['total_energy_supplied'] = float(flow_out.sum())
            
            # Results from dataframe if available
            if results_df is not None and not results_df.empty:
                summary['results_summary']['num_pipes'] = int(len(results_df))
                if 'Total Cost (€)' in results_df.columns:
                    summary['results_summary']['total_pipe_cost'] = float(results_df['Total Cost (€)'].sum())
                if 'Heat Flow (kW)' in results_df.columns:
                    summary['results_summary']['total_heat_flow_kW'] = float(results_df['Heat Flow (kW)'].sum())
                    summary['results_summary']['max_heat_flow_kW'] = float(results_df['Heat Flow (kW)'].max())
                if 'Electricity Flow (kW)' in results_df.columns:
                    summary['results_summary']['total_electricity_flow_kW'] = float(results_df['Electricity Flow (kW)'].sum())
                    summary['results_summary']['max_electricity_flow_kW'] = float(results_df['Electricity Flow (kW)'].max())
        
        except Exception as e:
            summary['results_summary']['error'] = f"Error extracting results: {str(e)}"
    
    # Save to JSON file
    output_path = os.path.join(output_folder, 'scenario_summary.json')
    with open(output_path, 'w') as f:
        json.dump(summary, f, indent=2, default=str)
    
    print(f"\nScenario summary saved to: {output_path}")
    
    return summary