"""
Results Processing Orchestrator

Main entry point for processing Calliope model results.
Coordinates the extraction, loss calculations, visualization, and export steps.
"""

import os

from .extract_model_data import (
    extract_coordinates_and_capacities,
    extract_unmet_demand
)
from .heat_loss_calculator import calculate_heat_network_losses
from .electricity_loss_calculator import calculate_electricity_network_losses
from .map_visualization import create_system_map
from .bill_of_materials import export_bill_of_materials


# Default configuration values
DEFAULT_DISTANCE_FACTORS = {
    'Heat transmission main': 1.0,
    'LQ heat distribution main': 1.0,
    'LQ heat distribution secondary': 1.0,
    'LV electricity distribution main': 1.0,
    'LV electricity distribution secondary': 1.0
}

DEFAULT_HEAT_LOSS_RATES = {
    'Heat transmission main': 65.8,      # W/m
    'LQ heat distribution main': 52,     # W/m
    'LQ heat distribution secondary': 29 # W/m
}

DEFAULT_ELECTRICITY_RESISTANCE_RATES = {
    'LV electricity distribution main': 0.247,       # Ω/km
    'LV electricity distribution secondary': 0.247   # Ω/km
}


def process_calliope_results(
    model,
    buildings_gdf,
    mode='plot',
    output_folder='outputs',
    heat_capacity=4.19,
    density=1000,
    delta_T=25,
    flow_speed=0.62,
    distance_factors=None,
    pipe_sizing_method='class',
    heat_loss_rates=None,
    apply_heat_losses=False,
    electricity_resistance_rates=None,
    apply_electricity_losses=False,
    substation_efficiency=0.9
):
    """
    Process Calliope model results, create visualizations, and export bill of materials.
    
    This is the main orchestrator function that coordinates all results processing steps:
    1. Extract model data (coordinates, capacities, demands)
    2. Calculate network losses (heat and/or electricity)
    3. Generate system map visualization (if mode='plot')
    4. Export bill of materials
    
    Parameters
    ----------
    model : calliope.Model
        Solved Calliope model with results.
    buildings_gdf : geopandas.GeoDataFrame
        GeoDataFrame with building geometries and heat demand data.
        Must contain 'id', 'Peak heat demand (kW)', and geometry columns.
    mode : str, optional
        Run mode: 'plot' to generate visualization, 'export' to skip visualization.
        Default: 'plot'.
    output_folder : str, optional
        Folder to save output files. Default: 'outputs'.
    heat_capacity : float, optional
        Heat capacity in kJ/kgK for pipe sizing. Default: 4.19.
    density : float, optional
        Density in kg/m³ for pipe sizing. Default: 1000.
    delta_T : float, optional
        Temperature difference in K for pipe sizing. Default: 25.
    flow_speed : float, optional
        Flow speed in m/s for pipe sizing. Default: 0.62.
    distance_factors : dict, optional
        Multiplication factors for distances by segment type. Default: all 1.0.
    pipe_sizing_method : str, optional
        Method for calculating pipe diameters. Default: 'class'.
        - 'class': Use maximum diameter within each segment type
        - 'individual': Round each pipe diameter individually to nearest 5mm
    heat_loss_rates : dict, optional
        Heat loss rates in W/m for each pipe type. Default: None.
    apply_heat_losses : bool, optional
        Whether to apply heat losses and recalculate capacities. Default: False.
    electricity_resistance_rates : dict, optional
        Resistance values in Ω/km for each cable type. Default: None.
    apply_electricity_losses : bool, optional
        Whether to apply electricity I²R losses. Default: False.
    substation_efficiency : float, optional
        Heat substation efficiency for HQ→LQ conversion. Default: 0.9.
    
    Returns
    -------
    tuple
        (export_df, total_system_losses_kw, total_LV_losses_kw, supply_losses,
         total_unmet_demand_kw, num_unmet_nodes, total_demand_nodes,
         total_LQ_losses_kw, total_HQ_losses_kw, substation_efficiency_losses_kw)
    
    Side Effects
    ------------
    - If mode=='plot', saves system_map.html to output_folder/
    - Saves bill_of_materials.csv to output_folder/
    """
    # Apply defaults
    if distance_factors is None:
        distance_factors = DEFAULT_DISTANCE_FACTORS.copy()
    
    if apply_heat_losses and heat_loss_rates is None:
        heat_loss_rates = DEFAULT_HEAT_LOSS_RATES.copy()
    
    if apply_electricity_losses and electricity_resistance_rates is None:
        electricity_resistance_rates = DEFAULT_ELECTRICITY_RESISTANCE_RATES.copy()
    
    # =========================================================================
    # 1. Extract model data
    # =========================================================================
    df_coords, df_capacity_coords = extract_coordinates_and_capacities(model)
    
    unmet_demand_by_node, total_unmet_demand_kw, num_unmet_nodes, total_demand_nodes = \
        extract_unmet_demand(model)
    
    # =========================================================================
    # 2. Calculate losses
    # =========================================================================
    # Initialize loss tracking variables
    adjusted_capacities = {}
    supply_losses = {}
    total_system_losses_kw = 0.0
    total_LQ_losses_kw = 0.0
    total_HQ_losses_kw = 0.0
    total_LV_losses_kw = 0.0
    substation_efficiency_losses_kw = 0.0
    
    # Heat network losses
    if apply_heat_losses and heat_loss_rates is not None:
        heat_results = calculate_heat_network_losses(
            df_capacity_coords=df_capacity_coords,
            model=model,
            buildings_gdf=buildings_gdf,
            distance_factors=distance_factors,
            heat_loss_rates=heat_loss_rates,
            substation_efficiency=substation_efficiency
        )
        
        adjusted_capacities.update(heat_results['adjusted_capacities'])
        supply_losses.update(heat_results['supply_losses'])
        total_system_losses_kw = heat_results['total_system_losses_kw']
        total_LQ_losses_kw = heat_results['total_LQ_losses_kw']
        total_HQ_losses_kw = heat_results['total_HQ_losses_kw']
        substation_efficiency_losses_kw = heat_results['substation_efficiency_losses_kw']
    
    # Electricity network losses
    if apply_electricity_losses and electricity_resistance_rates is not None:
        elec_results = calculate_electricity_network_losses(
            df_capacity_coords=df_capacity_coords,
            model=model,
            distance_factors=distance_factors,
            electricity_resistance_rates=electricity_resistance_rates
        )
        
        adjusted_capacities.update(elec_results['adjusted_capacities'])
        supply_losses.update(elec_results['supply_losses'])
        total_LV_losses_kw = elec_results['total_LV_losses_kw']
    
    # =========================================================================
    # 3. Generate visualization (if requested)
    # =========================================================================
    if mode == 'plot':
        loss_statistics = {
            'total_system_losses_kw': total_system_losses_kw,
            'total_LQ_losses_kw': total_LQ_losses_kw,
            'total_HQ_losses_kw': total_HQ_losses_kw,
            'substation_efficiency_losses_kw': substation_efficiency_losses_kw,
            'total_LV_losses_kw': total_LV_losses_kw
        }
        
        create_system_map(
            df_capacity_coords=df_capacity_coords,
            df_coords=df_coords,
            buildings_gdf=buildings_gdf,
            model=model,
            adjusted_capacities=adjusted_capacities,
            supply_losses=supply_losses,
            unmet_demand_by_node=unmet_demand_by_node,
            loss_statistics=loss_statistics,
            output_folder=output_folder,
            apply_heat_losses=apply_heat_losses,
            apply_electricity_losses=apply_electricity_losses
        )
    
    # =========================================================================
    # 4. Export bill of materials
    # =========================================================================
    pipe_sizing_params = {
        'heat_capacity': heat_capacity,
        'density': density,
        'delta_T': delta_T,
        'flow_speed': flow_speed
    }
    
    export_df = export_bill_of_materials(
        model=model,
        adjusted_capacities=adjusted_capacities,
        supply_losses=supply_losses,
        distance_factors=distance_factors,
        output_folder=output_folder,
        pipe_sizing_params=pipe_sizing_params,
        pipe_sizing_method=pipe_sizing_method,
        apply_losses=(apply_heat_losses or apply_electricity_losses)
    )
    
    # =========================================================================
    # 5. Return results
    # =========================================================================
    return (
        export_df,
        total_system_losses_kw,
        total_LV_losses_kw,
        supply_losses,
        total_unmet_demand_kw,
        num_unmet_nodes,
        total_demand_nodes,
        total_LQ_losses_kw,
        total_HQ_losses_kw,
        substation_efficiency_losses_kw
    )
