"""
Network Topology Module

Functions for loading and processing network infrastructure:
- Stedin grid data (gas, electricity, transformers)
- OSM road network extraction
- Transmission node creation
- Geographic utilities
"""

from .process_stedin_grids import (
    fetch_stedin_layer_from_arcgis,
    load_stedin_grids_from_cache,
    process_network_topology
)
from .process_osm_roads import (
    extract_osm_roads,
    OSMExtractionError
)
from .create_transmission_nodes import create_transmission_nodes
from .grid_utils import haversine_distance, interpolate_line

__all__ = [
    'fetch_stedin_layer_from_arcgis',
    'load_stedin_grids_from_cache',
    'process_network_topology',
    'extract_osm_roads',
    'OSMExtractionError',
    'create_transmission_nodes',
    'haversine_distance',
    'interpolate_line',
]
