"""
Results Processing Module

This package contains functions for processing Calliope model results,
including loss calculations, visualizations, and bill of materials export.
"""

from .orchestrator import process_calliope_results
from .extract_model_data import (
    extract_coordinates_and_capacities,
    build_demand_lookup,
    extract_unmet_demand
)
from .heat_loss_calculator import calculate_heat_network_losses
from .electricity_loss_calculator import calculate_electricity_network_losses
from .map_visualization import create_system_map
from .bill_of_materials import export_bill_of_materials

__all__ = [
    'process_calliope_results',
    'extract_coordinates_and_capacities',
    'build_demand_lookup',
    'extract_unmet_demand',
    'calculate_heat_network_losses',
    'calculate_electricity_network_losses',
    'create_system_map',
    'export_bill_of_materials'
]
