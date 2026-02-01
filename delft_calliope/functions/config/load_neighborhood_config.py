"""
Neighborhood Configuration Loader

This module handles loading neighborhood-specific parameters from the
neighborhoods configuration YAML file.
"""

import yaml
import os


def load_neighborhoods_config(config_file='inputs/neighborhoods_config.yaml'):
    """
    Load neighborhoods configuration from YAML file.
    
    Parameters
    ----------
    config_file : str
        Path to the neighborhoods configuration YAML file
    
    Returns
    -------
    dict
        Parsed YAML configuration
    
    Raises
    ------
    FileNotFoundError
        If config file doesn't exist
    ValueError
        If YAML parsing fails
    """
    if not os.path.exists(config_file):
        raise FileNotFoundError(f"Neighborhoods config file not found: {config_file}")
    
    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
            if not config or 'neighborhoods' not in config:
                raise ValueError("Invalid config structure: 'neighborhoods' key not found")
            return config
    except yaml.YAMLError as e:
        raise ValueError(f"Error parsing neighborhoods config: {e}")


def get_neighborhood_params(neighborhood, year, config_file='inputs/neighborhoods_config.yaml'):
    """
    Get parameters for a specific neighborhood and year.
    
    Parameters
    ----------
    neighborhood : str
        Neighborhood identifier (e.g., 'multatulibuurt', 'holstbuurt')
    year : int
        Year for heat demand data (e.g., 2013, 2019, 2020)
    config_file : str, optional
        Path to neighborhoods config file
    
    Returns
    -------
    dict
        Dictionary containing:
        - 'name': Full neighborhood name
        - 'area': TNO API area code for heat demand
        - 'year': Year (same as input)
        - 'bbox_coords': List of (lon, lat) tuples defining the polygon
        - 'substation_coords': [lon, lat] for the substation location
    
    Raises
    ------
    ValueError
        If neighborhood or year not found in config
    """
    config = load_neighborhoods_config(config_file)
    
    # Validate neighborhood
    if neighborhood not in config['neighborhoods']:
        available = list(config['neighborhoods'].keys())
        raise ValueError(
            f"Unknown neighborhood: '{neighborhood}'. "
            f"Available neighborhoods: {', '.join(available)}"
        )
    
    neighborhood_data = config['neighborhoods'][neighborhood]
    
    # Validate year
    if 'year' not in neighborhood_data:
        raise ValueError(f"No year data configured for neighborhood: {neighborhood}")
    
    if year not in neighborhood_data['year']:
        available_years = list(neighborhood_data['year'].keys())
        raise ValueError(
            f"Year {year} not configured for {neighborhood}. "
            f"Available years: {', '.join(map(str, available_years))}"
        )
    
    # Get area code for the specified year
    area = neighborhood_data['year'][year]
    
    # Convert bbox_coords from list of lists to list of tuples
    bbox_coords = [tuple(coord) for coord in neighborhood_data['bbox_coords']]
    
    # Get substation coordinates
    substation_coords = neighborhood_data.get('substation_coords')
    if substation_coords is None:
        raise ValueError(f"No substation_coords configured for neighborhood: {neighborhood}")
    
    return {
        'name': neighborhood_data['name'],
        'area': area,
        'year': year,
        'bbox_coords': bbox_coords,
        'substation_coords': substation_coords,
        'neighborhood_id': neighborhood
    }


def list_available_neighborhoods(config_file='inputs/neighborhoods_config.yaml'):
    """
    List all available neighborhoods and their configured years.
    
    Parameters
    ----------
    config_file : str, optional
        Path to neighborhoods config file
    
    Returns
    -------
    dict
        Dictionary mapping neighborhood IDs to their details
    """
    config = load_neighborhoods_config(config_file)
    
    result = {}
    for neighborhood_id, data in config['neighborhoods'].items():
        result[neighborhood_id] = {
            'name': data['name'],
            'years': list(data.get('year', {}).keys())
        }
    
    return result


def validate_neighborhood_config(config_file='inputs/neighborhoods_config.yaml'):
    """
    Validate that the neighborhoods config file has all required fields.
    
    Parameters
    ----------
    config_file : str, optional
        Path to neighborhoods config file
    
    Returns
    -------
    tuple
        (is_valid, errors)
        - is_valid (bool): True if valid, False otherwise
        - errors (list): List of error messages
    """
    errors = []
    
    try:
        config = load_neighborhoods_config(config_file)
    except Exception as e:
        return False, [str(e)]
    
    required_fields = ['name', 'bbox_coords', 'year', 'substation_coords']
    
    for neighborhood_id, data in config['neighborhoods'].items():
        for field in required_fields:
            if field not in data:
                errors.append(f"Neighborhood '{neighborhood_id}' missing required field: '{field}'")
        
        # Validate bbox_coords structure
        if 'bbox_coords' in data:
            if not isinstance(data['bbox_coords'], list) or len(data['bbox_coords']) < 3:
                errors.append(f"Neighborhood '{neighborhood_id}': bbox_coords must be a list of at least 3 coordinate pairs")
            else:
                for i, coord in enumerate(data['bbox_coords']):
                    if not isinstance(coord, list) or len(coord) != 2:
                        errors.append(f"Neighborhood '{neighborhood_id}': bbox_coords[{i}] must be [lon, lat]")
        
        # Validate substation_coords structure
        if 'substation_coords' in data:
            if not isinstance(data['substation_coords'], list) or len(data['substation_coords']) != 2:
                errors.append(f"Neighborhood '{neighborhood_id}': substation_coords must be [lon, lat]")
        
        # Validate year structure
        if 'year' in data:
            if not isinstance(data['year'], dict) or len(data['year']) == 0:
                errors.append(f"Neighborhood '{neighborhood_id}': 'year' must be a dict with at least one year mapping")
    
    return len(errors) == 0, errors
