"""
BAG Addresses API Interface

This module enriches building data with address information from the Dutch BAG 
(Basisregistratie Adressen en Gebouwen) API, consolidating multiple addresses
per building into readable format.
"""

import requests
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict


# Configure module logger
logger = logging.getLogger(__name__)


class BAGAddressError(Exception):
    """Exception raised for BAG address API errors."""
    
    def __init__(self, message, status_code=None, building_id=None):
        self.status_code = status_code
        self.building_id = building_id
        super().__init__(message)


def _get_api_key():
    """
    Retrieve BAG API key from environment variable.
    
    Returns
    -------
    str or None
        API key if found in environment, None otherwise.
    """
    return os.environ.get('BAG_API_KEY')


def enrich_buildings_with_addresses(all_buildings, api_key=None):
    """
    Fetches and consolidates addresses for each building in all_buildings using the BAG API.

    Parameters
    ----------
    all_buildings : list
        List of building dicts from BAG API.
    api_key : str, optional
        API key for BAG Individuele Bevragingen. If not provided, will attempt
        to read from BAG_API_KEY environment variable.

    Returns
    -------
    dict
        {pand_id: {'address': str, 'aantal_adressen': int}}
    
    Raises
    ------
    BAGAddressError
        If API request fails due to authentication or rate limiting.
    ValueError
        If no API key is provided or found in environment.
    """
    # Resolve API key
    resolved_key = api_key or _get_api_key()
    if not resolved_key:
        raise ValueError(
            "BAG API key required. Either pass api_key parameter or set "
            "BAG_API_KEY environment variable."
        )
    
    addresses_url = "https://api.bag.kadaster.nl/lvbag/individuelebevragingen/v2/adressen"
    session = requests.Session()
    session.headers.update({
        "X-Api-Key": resolved_key,
        "Accept": "application/hal+json",
        "Accept-Crs": "epsg:28992",
        "Content-Crs": "epsg:28992"
    })

    # Extract unique building IDs
    building_ids = []
    for b in all_buildings:
        pand_id = None
        if 'pand' in b and isinstance(b['pand'], dict):
            pand_id = b['pand'].get('identificatie')
        elif 'identificatie' in b:
            pand_id = b.get('identificatie')
        if pand_id and pand_id not in building_ids:
            building_ids.append(pand_id)

    # Track statistics for logging
    stats = {
        'success': 0,
        'not_found': 0,
        'errors': 0,
        'rate_limited': 0
    }

    def fetch_addresses_for_building(pand_id):
        """Fetch addresses for a single building with proper error handling."""
        addresses = []
        page = 1
        max_retries = 3
        
        while True:
            for attempt in range(max_retries):
                try:
                    params = {
                        "pandIdentificatie": pand_id,
                        "page": page,
                        "pageSize": 100
                    }
                    response = session.get(addresses_url, params=params, timeout=10)
                    
                    # Handle specific HTTP status codes
                    if response.status_code == 200:
                        data = response.json()
                        if '_embedded' in data and 'adressen' in data['_embedded']:
                            page_addresses = data['_embedded']['adressen']
                            addresses.extend(page_addresses)
                            if len(page_addresses) < 100:
                                stats['success'] += 1
                                return pand_id, addresses, None
                            page += 1
                            break
                        else:
                            stats['success'] += 1
                            return pand_id, addresses, None
                    
                    elif response.status_code == 404:
                        # Building has no registered addresses - this is normal
                        stats['not_found'] += 1
                        return pand_id, [], None
                    
                    elif response.status_code == 401:
                        error = BAGAddressError(
                            "Authentication failed. Check your BAG API key.",
                            status_code=401,
                            building_id=pand_id
                        )
                        return pand_id, [], error
                    
                    elif response.status_code == 429:
                        stats['rate_limited'] += 1
                        if attempt < max_retries - 1:
                            wait_time = (attempt + 1) * 2  # Exponential backoff
                            logger.warning(
                                f"Rate limited for building {pand_id}, "
                                f"waiting {wait_time}s (attempt {attempt + 1}/{max_retries})"
                            )
                            time.sleep(wait_time)
                            continue
                        else:
                            error = BAGAddressError(
                                "Rate limit exceeded after retries",
                                status_code=429,
                                building_id=pand_id
                            )
                            return pand_id, [], error
                    
                    else:
                        # Other HTTP errors
                        logger.warning(
                            f"HTTP {response.status_code} for building {pand_id}: "
                            f"{response.text[:100]}"
                        )
                        if attempt < max_retries - 1:
                            time.sleep(0.3)
                            continue
                        else:
                            stats['errors'] += 1
                            return pand_id, [], None
                            
                except requests.exceptions.Timeout:
                    logger.warning(f"Timeout for building {pand_id} (attempt {attempt + 1})")
                    if attempt < max_retries - 1:
                        time.sleep(0.3)
                        continue
                    else:
                        stats['errors'] += 1
                        return pand_id, [], None
                        
                except requests.exceptions.ConnectionError as e:
                    logger.warning(f"Connection error for building {pand_id}: {e}")
                    if attempt < max_retries - 1:
                        time.sleep(0.3)
                        continue
                    else:
                        stats['errors'] += 1
                        return pand_id, [], None
            else:
                break
                
        return pand_id, addresses, None

    def parse_address_components(addr_data):
        if isinstance(addr_data, dict):
            addr = addr_data.get('nummeraanduiding', addr_data)
            return {
                'korteNaam': addr.get('korteNaam', ''),
                'huisnummer': addr.get('huisnummer'),
                'huisletter': addr.get('huisletter', ''),
                'huisnummertoevoeging': addr.get('huisnummertoevoeging', '')
            }
        return None

    def consolidate_addresses(raw_addresses):
        if not raw_addresses:
            return ''
        parsed = []
        for addr in raw_addresses:
            components = parse_address_components(addr)
            if components and components['huisnummer'] is not None:
                parsed.append(components)
        if not parsed:
            return ''
        street_groups = defaultdict(list)
        for addr in parsed:
            street_groups[addr['korteNaam']].append(addr)
        result_parts = []
        for street_name, addresses in street_groups.items():
            house_numbers = [addr['huisnummer'] for addr in addresses]
            if len(house_numbers) == 1:
                addr = addresses[0]
                parts = [street_name, str(addr['huisnummer'])]
                if addr['huisletter']:
                    parts.append(addr['huisletter'])
                if addr['huisnummertoevoeging']:
                    parts.append(addr['huisnummertoevoeging'])
                result_parts.append(' '.join(parts))
            else:
                min_num = min(house_numbers)
                max_num = max(house_numbers)
                result_parts.append(f"{street_name} {min_num}-{max_num}")
        return ', '.join(result_parts)

    # Parallel address fetching
    building_addresses = {}
    critical_error = None
    
    with ThreadPoolExecutor(max_workers=2) as executor:
        future_to_building = {
            executor.submit(fetch_addresses_for_building, bid): bid 
            for bid in building_ids
        }
        for future in as_completed(future_to_building):
            pand_id, raw_addresses, error = future.result()
            
            # Check for critical errors (auth failure)
            if error and error.status_code == 401:
                critical_error = error
                # Don't break - let other futures complete to avoid hanging threads
            
            consolidated_address = consolidate_addresses(raw_addresses)
            building_addresses[pand_id] = {
                'address': consolidated_address,
                'aantal_adressen': len(raw_addresses)
            }
    
    # Log summary statistics
    total = len(building_ids)
    logger.info(
        f"Address fetch complete: {stats['success']} success, "
        f"{stats['not_found']} not found, {stats['errors']} errors "
        f"out of {total} buildings"
    )
    
    if stats['rate_limited'] > 0:
        logger.warning(f"Encountered {stats['rate_limited']} rate limit responses")
    
    # Raise critical errors after all threads complete
    if critical_error:
        raise critical_error

    return building_addresses
