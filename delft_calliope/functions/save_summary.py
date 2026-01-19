import json
import os
from datetime import datetime

def save_scenario_summary(config, model, results_df, output_folder, execution_times, 
                          apply_heat_losses=False, total_system_losses_kw=0.0,
                          apply_electricity_losses=False, total_electricity_losses_kw=0.0,
                          supply_losses=None, total_unmet_demand_kw=0.0, num_unmet_nodes=0, total_demand_nodes=0,
                          connectivity_info=None):
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
    apply_heat_losses : bool, optional
        Whether heat losses were applied (default: False)
    total_system_losses_kw : float, optional
        Total system heat losses in kW (default: 0.0)
    apply_electricity_losses : bool, optional
        Whether electricity losses were applied (default: False)
    total_electricity_losses_kw : float, optional
        Total electricity losses in kW (default: 0.0)
    supply_losses : dict, optional
        Dictionary of losses per supply node (default: None)
    total_unmet_demand_kw : float, optional
        Total unmet demand in kW (default: 0.0)
    num_unmet_nodes : int, optional
        Number of demand nodes with unmet demand (default: 0)
    total_demand_nodes : int, optional
        Total number of demand nodes (default: 0)
    connectivity_info : dict, optional
        Network connectivity information including isolated nodes (default: None)
    """
    
    if supply_losses is None:
        supply_losses = {}
    
    if connectivity_info is None:
        connectivity_info = {
            'num_isolated_demand_nodes': 0,
            'isolated_demand_nodes': [],
            'total_demand_nodes': 0
        }
    
    summary = {
        # Scenario identification
        'scenario_info': {
            'neighborhood_name': config.get('neighborhood_name', ''),
            'year': config['year'],
            'scenario_type': config['scenario'],
            'topology_source': config['topology_source'],
            'timestamp': datetime.now().isoformat(),
            'spacing_m': config.get('spacing_m'),
        },
        
        # Technology parameters
        'technology_parameters': config['tech_efficiencies'],
        
        # Postprocessing parameters
        'postprocessing_parameters': {
            'pipe_sizing': config['postprocessing']['pipe_sizing'],
            'distance_factors': config['postprocessing']['distance_factors'],
            'heat_loss_rates': config['postprocessing']['heat_loss_rates'],
            'electricity_resistance_rates': config['postprocessing']['electricity_resistance_rates'],
        },
        
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
        },
        
        # Heat loss information
        'heat_loss_info': {
            'apply_heat_losses': apply_heat_losses,
            'total_system_losses_kw': total_system_losses_kw,
        },
        
        # Electricity loss information (NEW)
        'electricity_loss_info': {
            'apply_electricity_losses': apply_electricity_losses,
            'total_lv_losses_kw': total_electricity_losses_kw,
        },
        
        # Unmet demand information
        'unmet_demand_info': {
            'total_unmet_demand_kw': total_unmet_demand_kw,
            'num_unmet_nodes': num_unmet_nodes,
            'total_demand_nodes': total_demand_nodes,
            'unmet_demand_fraction': f"{num_unmet_nodes}/{total_demand_nodes}" if total_demand_nodes > 0 else "0/0",
        },
        
        # Network connectivity information
        'connectivity_info': {
            'num_isolated_demand_nodes_requiring_bridges': connectivity_info.get('num_isolated_demand_nodes', 0),
            'isolated_demand_nodes_list': connectivity_info.get('isolated_demand_nodes', []),
            'total_demand_nodes_in_network': connectivity_info.get('total_demand_nodes', 0),
            'connectivity_status': 'fully_connected' if connectivity_info.get('num_isolated_demand_nodes', 0) == 0 else 'partially_connected_with_emergency_links',
        },
        
        # Supply/transformer losses
        'supply_losses': supply_losses
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
                    geothermal_cap_original = float(flow_caps.sel(techs='supply_geothermal').sum())
                    
                    # Apply heat losses if calculated
                    if apply_heat_losses and 'geothermie_delft' in supply_losses:
                        geothermal_cap_adjusted = geothermal_cap_original + supply_losses['geothermie_delft']
                        summary['results_summary']['supply_geothermal_capacity_original_kW'] = geothermal_cap_original
                        summary['results_summary']['supply_geothermal_capacity_adjusted_kW'] = geothermal_cap_adjusted
                        summary['results_summary']['supply_geothermal_additional_for_losses_kW'] = supply_losses['geothermie_delft']
                    else:
                        summary['results_summary']['supply_geothermal_capacity_kW'] = geothermal_cap_original
                        
                except (KeyError, ValueError):
                    summary['results_summary']['supply_geothermal_capacity_kW'] = 0.0
                    
                try:
                    heat_pump_cap = float(flow_caps.sel(techs='heat_pump').sum())
                    summary['results_summary']['heat_pump_capacity_kW'] = heat_pump_cap
                except (KeyError, ValueError):
                    summary['results_summary']['heat_pump_capacity_kW'] = 0.0
                
                # Add total heat pump electricity consumption capacity
                try:
                    heat_pump_elec_cap = float(model.results.flow_cap.sel(techs='heat_pump', carriers='electricity').sum())
                    summary['results_summary']['heat_pump_electricity_capacity_kW'] = heat_pump_elec_cap
                except (KeyError, ValueError):
                    summary['results_summary']['heat_pump_electricity_capacity_kW'] = 0.0
                
                # Add supply electricity capacity
                try:
                    supply_elec_cap = float(flow_caps.sel(techs='supply_LV_electricity').sum())
                    
                    # Apply electricity losses if calculated
                    if apply_electricity_losses and total_electricity_losses_kw > 0:
                        supply_elec_cap_adjusted = supply_elec_cap + total_electricity_losses_kw
                        summary['results_summary']['supply_LV_electricity_capacity_original_kW'] = supply_elec_cap
                        summary['results_summary']['supply_LV_electricity_capacity_adjusted_kW'] = supply_elec_cap_adjusted
                        summary['results_summary']['supply_LV_electricity_additional_for_losses_kW'] = total_electricity_losses_kw
                    else:
                        summary['results_summary']['supply_LV_electricity_capacity_kW'] = supply_elec_cap
                        
                except (KeyError, ValueError):
                    summary['results_summary']['supply_LV_electricity_capacity_kW'] = 0.0
                    
                try:
                    heat_demand = abs(float(model.results['flow_in'].sel(techs='demand_LQ_heat').sum()))
                    summary['results_summary']['total_heat_demand_kW'] = heat_demand
                except (KeyError, ValueError):
                    summary['results_summary']['total_heat_demand_kW'] = 0.0
                
                # Add unmet demand as fraction of total demand
                if total_unmet_demand_kw > 0:
                    heat_demand = summary['results_summary'].get('total_heat_demand_kW', 0.0)
                    summary['results_summary']['total_unmet_demand_kW_fraction'] = f"{total_unmet_demand_kw:,.0f}/{heat_demand:,.0f} kW"
                    summary['results_summary']['unmet_nodes_fraction'] = f"{num_unmet_nodes}/{total_demand_nodes}"

                # Add heat loss summary if applicable
                if apply_heat_losses and total_system_losses_kw > 0:
                    summary['results_summary']['heat_losses'] = {
                        'total_system_losses_kW': total_system_losses_kw,
                        'loss_percentage': (total_system_losses_kw / heat_demand * 100) if heat_demand > 0 else 0.0,
                        'supply_node_losses': supply_losses
                    }

                # Add electricity loss summary if applicable
                if apply_electricity_losses and total_electricity_losses_kw > 0:
                    # Get total heat pump electricity demand from model
                    try:
                        total_hp_elec = abs(float(
                            model.results.flow_cap
                            .sel(techs='heat_pump', carriers='electricity')
                            .sum()
                        ))
                    except (KeyError, ValueError):
                        total_hp_elec = 0.0
                    
                    summary['results_summary']['electricity_losses'] = {
                        'total_lv_losses_kW': total_electricity_losses_kw,
                        'loss_percentage': (total_electricity_losses_kw / total_hp_elec * 100) if total_hp_elec > 0 else 0.0,
                    }

                # District heating efficiency (only when heat pump is not used)
                if summary['results_summary'].get('heat_pump_capacity_kW', 0) == 0.0:
                    # Use adjusted capacity if available, otherwise use original
                    if apply_heat_losses and 'geothermie_delft' in supply_losses:
                        geothermal_cap = geothermal_cap_adjusted
                    else:
                        geothermal_cap = geothermal_cap_original
                    
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
    
    #print(f"\nScenario summary saved to: {output_path}")
    
    return summary