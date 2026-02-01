"""
Data Acquisition Module

Functions for fetching raw data from external APIs and caches:
- BAG API for building footprints and addresses
- TNO API for heat demand profiles
"""

from .BAG_buildings_API import (
    fetch_buildings_from_BAG,
    load_buildings_from_cache,
    BAGAPIError
)
from .BAG_addresses_API import (
    enrich_buildings_with_addresses,
    BAGAddressError
)
from .TNO_API import (
    fetch_residential_heat_demand,
    TNOAPIError
)

__all__ = [
    'fetch_buildings_from_BAG',
    'load_buildings_from_cache',
    'BAGAPIError',
    'enrich_buildings_with_addresses',
    'BAGAddressError',
    'fetch_residential_heat_demand',
    'TNOAPIError',
]
