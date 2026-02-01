"""
YAML Configuration Loader for run_analysis.py

This module handles loading and parsing the YAML configuration file
that provides default settings for the analysis script.
"""

import yaml
import os

from functions.config.parse_arguments import DEFAULT_CONFIG_PATH


def load_config(config_path=None):
    """
    Load configuration from YAML file.
    
    Reads the YAML configuration and converts it to a flat dictionary
    format expected by the analysis workflow functions.
    
    Parameters
    ----------
    config_path : str, optional
        Path to YAML config file. Uses DEFAULT_CONFIG_PATH if not specified.
    
    Returns
    -------
    dict
        Configuration dictionary in the flat format expected by the workflow.
    
    Raises
    ------
    FileNotFoundError
        If the specified configuration file does not exist
    yaml.YAMLError
        If the configuration file contains invalid YAML
    """
    if config_path is None:
        config_path = DEFAULT_CONFIG_PATH
    
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Configuration file not found: {config_path}")
    
    with open(config_path, 'r', encoding='utf-8') as f:
        yaml_config = yaml.safe_load(f)
    
    # Convert YAML structure to flat CONFIG format expected by the workflow
    config = {
        # Scenario selection
        'neighborhood': yaml_config['scenario']['neighborhood'],
        'year': yaml_config['scenario']['year'],
        'scenario': yaml_config['scenario']['type'],
        'topology_source': yaml_config['scenario']['topology_source'],
        
        # Execution settings
        'mode': yaml_config['execution']['mode'],
        'debug_single_node': yaml_config['execution']['debug_single_node'],
        'spacing_m': yaml_config['execution']['spacing_m'],
        
        # Data sources
        'online': yaml_config['data_sources']['online'],
        'bag_api_key': yaml_config['data_sources'].get('bag_api_key'),
        
        # Paths
        'heat_demand_csv_path': yaml_config['paths']['heat_demand_csv_path'],
        'bag_cache_path': yaml_config['paths']['bag_cache_path'],
        'stedin_cache_path': yaml_config['paths']['stedin_cache_path'],
        'inputs_folder': yaml_config['paths']['inputs_folder'],
        'data_tables_folder': yaml_config['paths']['data_tables_folder'],
        'outputs_folder': yaml_config['paths']['outputs_folder'],
        'debug_folder': yaml_config['paths']['debug_folder'],
        
        # Technology efficiencies
        'heat_pump_cop': yaml_config['tech_efficiencies']['heat_pump_cop'],
        'heat_substation_eff': yaml_config['tech_efficiencies']['heat_substation_eff'],
        'hybrid_threshold_kW': yaml_config['tech_efficiencies']['hybrid_threshold_kW'],
        
        # Postprocessing - pipe sizing
        'heat_capacity': yaml_config['postprocessing']['pipe_sizing']['heat_capacity'],
        'density': yaml_config['postprocessing']['pipe_sizing']['density'],
        'delta_T': yaml_config['postprocessing']['pipe_sizing']['delta_T'],
        'flow_speed': yaml_config['postprocessing']['pipe_sizing']['flow_speed'],
        'pipe_sizing_method': yaml_config['postprocessing']['pipe_sizing_method'],
        
        # Postprocessing - distance factors and loss rates
        'distance_factors': yaml_config['postprocessing']['distance_factors'],
        'heat_loss_rates': yaml_config['postprocessing']['heat_loss_rates'],
        'apply_heat_losses': yaml_config['postprocessing']['apply_heat_losses'],
        'electricity_resistance_rates': yaml_config['postprocessing']['electricity_resistance_rates'],
        'apply_electricity_losses': yaml_config['postprocessing']['apply_electricity_losses'],
        
        # Link parameters
        'link_parameters': yaml_config['link_parameters'],
        'transformer_supply_capacity': yaml_config['transformer_supply_capacity'],
        
        # Keep nested structures for functions that expect them
        'tech_efficiencies': yaml_config['tech_efficiencies'],
        'postprocessing': yaml_config['postprocessing'],
    }
    
    return config
