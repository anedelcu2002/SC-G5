"""
CLI Override Helper for run_analysis.py

This module provides a function to apply command line argument overrides
to the configuration dictionary loaded from YAML.
"""


def apply_cli_overrides(config, args):
    """
    Apply CLI argument overrides to configuration dictionary.
    
    CLI arguments take precedence over values loaded from the YAML config file.
    Only non-None argument values are applied as overrides.
    
    Parameters
    ----------
    config : dict
        Configuration dictionary loaded from YAML
    args : argparse.Namespace
        Parsed command line arguments
    
    Returns
    -------
    dict
        Updated configuration dictionary with CLI overrides applied
    """
    
    # Simple top-level overrides: arg_name -> config_key
    simple_overrides = {
        'neighborhood': 'neighborhood',
        'year': 'year',
        'scenario': 'scenario',
        'mode': 'mode',
        'spacing': 'spacing_m',
        'topology_source': 'topology_source',
        'output_folder': 'outputs_folder',
        'data_tables_folder': 'data_tables_folder',
        'debug_folder': 'debug_folder',
    }
    
    # Nested overrides: arg_name -> (path_list, key)
    # path_list is the sequence of keys to traverse, key is the final key to set
    nested_overrides = {
        # Tech efficiencies
        'threshold': (['tech_efficiencies'], 'hybrid_threshold_kW'),
        'heat_pump_cop': (['tech_efficiencies'], 'heat_pump_cop'),
        'heat_substation_eff': (['tech_efficiencies'], 'heat_substation_eff'),
        
        # Postprocessing - pipe sizing method
        'pipe_sizing': (['postprocessing'], 'pipe_sizing_method'),
        
        # Postprocessing - pipe sizing parameters
        'delta_t': (['postprocessing', 'pipe_sizing'], 'delta_T'),
        'flow_speed': (['postprocessing', 'pipe_sizing'], 'flow_speed'),
        
        # Postprocessing - distance factors
        'distance_factor_heat_trans_main': (['postprocessing', 'distance_factors'], 'Heat transmission main'),
        'distance_factor_heat_dist_main': (['postprocessing', 'distance_factors'], 'LQ heat distribution main'),
        'distance_factor_heat_dist_sec': (['postprocessing', 'distance_factors'], 'LQ heat distribution secondary'),
        'distance_factor_elec_dist_main': (['postprocessing', 'distance_factors'], 'LV electricity distribution main'),
        'distance_factor_elec_dist_sec': (['postprocessing', 'distance_factors'], 'LV electricity distribution secondary'),
        
        # Postprocessing - heat loss rates
        'heat_loss_rate_trans_main': (['postprocessing', 'heat_loss_rates'], 'Heat transmission main'),
        'heat_loss_rate_dist_main': (['postprocessing', 'heat_loss_rates'], 'LQ heat distribution main'),
        'heat_loss_rate_dist_sec': (['postprocessing', 'heat_loss_rates'], 'LQ heat distribution secondary'),
        
        # Postprocessing - electricity resistance rates
        'elec_resistance_main': (['postprocessing', 'electricity_resistance_rates'], 'LV electricity distribution main'),
        'elec_resistance_sec': (['postprocessing', 'electricity_resistance_rates'], 'LV electricity distribution secondary'),
        
        # Postprocessing - loss calculation flags
        'apply_heat_losses': (['postprocessing'], 'apply_heat_losses'),
        'apply_electricity_losses': (['postprocessing'], 'apply_electricity_losses'),
    }
    
    # Apply simple top-level overrides
    for arg_name, config_key in simple_overrides.items():
        value = getattr(args, arg_name, None)
        if value is not None:
            config[config_key] = value
    
    # Handle debug flag specially (it's a boolean flag, not None-able)
    if getattr(args, 'debug', False):
        config['debug_single_node'] = True
    
    # Apply nested overrides
    for arg_name, (path, key) in nested_overrides.items():
        value = getattr(args, arg_name, None)
        if value is not None:
            # Navigate to the nested dict
            target = config
            for p in path:
                target = target[p]
            target[key] = value
    
    # Handle online mode and API key specially
    if getattr(args, 'online', False):
        config['online'] = True
        bag_api_key = getattr(args, 'bag_api_key', None)
        if bag_api_key:
            config['BAG_API_KEY'] = bag_api_key
    
    return config


def validate_online_mode(args):
    """
    Validate that online mode has required API key.
    
    Parameters
    ----------
    args : argparse.Namespace
        Parsed command line arguments
    
    Returns
    -------
    bool
        True if validation passes, False if online mode is requested without API key
    str or None
        Error message if validation fails, None otherwise
    """
    if getattr(args, 'online', False) and not getattr(args, 'bag_api_key', None):
        error_msg = (
            "\nERROR: Online mode requires a BAG API key.\n"
            "Please provide your API key using --bag-api-key YOUR_KEY\n"
            "Obtain a key from: https://www.kadaster.nl/zakelijk/producten/adressen-en-gebouwen/bag-api\n"
            "\nAlternatively, run in offline mode (default) using cached data."
        )
        return False, error_msg
    return True, None
