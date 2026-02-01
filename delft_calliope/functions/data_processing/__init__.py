"""
Data Processing Module

Functions for processing raw data into analysis-ready formats:
- Building DataFrame creation and visualization
- Heat demand merging and processing
"""

from .process_buildings import process_and_visualize_buildings
from .process_heat_demand import process_heat_demand

__all__ = [
    'process_and_visualize_buildings',
    'process_heat_demand',
]
