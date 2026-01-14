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
            'neighborhood_name': config.get('neighborhood_name', ''),
            'year': config['year'],
            'scenario_type': config['scenario'],
            'topology_source': config['topology_source'],
            'timestamp': datetime.now().isoformat(),
        },
        
        # Technology parameters
        'technology_parameters': config['tech_efficiencies'],
        
        # Model size and complexity
        'model_size': {
            'num_nodes': int(len(model.inputs.coords.get('nodes', []))),
            'num_techs': int(len(model.inputs.coords.get('techs', []))),
            'num_carriers': int(len(model.inputs.coords.get('carriers', []))),
            'num_links': int((model.inputs.base_tech == "transmission").sum()) if 'base_tech' in model.inputs else 0,
        },
        
        # Results summary
        'results_summary': {},
        
        # Execution times
        'execution_time': {
            'total_seconds': sum(execution_times.values()),
        }
    }
    
    # Add results summary if model was solved successfully
    if hasattr(model, 'results') and len(model.results.data_vars) > 0:
        try:
            # Capacity information
            if 'flow_cap' in model.results:
                flow_caps = model.results['flow_out']
                summary['results_summary']['total_capacity_installed'] = float(flow_caps.sum())
                
                # Capacity by tech
                try:
                    geothermal_cap = float(flow_caps.sel(techs='supply_geothermal').sum())
                    summary['results_summary']['supply_geothermal_capacity_kW'] = geothermal_cap
                except (KeyError, ValueError):
                    summary['results_summary']['supply_geothermal_capacity_kW'] = 0.0
                try:
                    heat_pump_cap = float(flow_caps.sel(techs='heat_pump').sum())
                    summary['results_summary']['heat_pump_capacity_kW'] = heat_pump_cap
                except (KeyError, ValueError):
                    summary['results_summary']['heat_pump_capacity_kW'] = 0.0
                try:
                    heat_demand = abs(float(model.results['flow_in'].sel(techs='demand_LQ_heat').sum()))
                    summary['results_summary']['total_heat_demand_kW'] = heat_demand
                except (KeyError, ValueError):
                    summary['results_summary']['total_heat_demand_kW'] = 0.0

                # District heating efficiency (only when heat pump is not used)
                if summary['results_summary'].get('heat_pump_capacity_kW', 0) == 0.0:
                    geothermal_cap = summary['results_summary'].get('supply_geothermal_capacity_kW', 0.0)
                    heat_demand = summary['results_summary'].get('total_heat_demand_kW', 0.0)
                    
                    if geothermal_cap > 0:
                        district_heating_efficiency = heat_demand / geothermal_cap
                        summary['results_summary']['district_heating_efficiency'] = district_heating_efficiency
                    else:
                        summary['results_summary']['district_heating_efficiency'] = None
                else:
                    summary['results_summary']['district_heating_efficiency'] = None

        except Exception as e:
            summary['results_summary']['error'] = f"Error extracting results: {str(e)}"
    
    # Save to JSON file
    output_path = os.path.join(output_folder, 'scenario_summary.json')
    with open(output_path, 'w') as f:
        json.dump(summary, f, indent=2, default=str)
    
    print(f"\nScenario summary saved to: {output_path}")
    
    return summary