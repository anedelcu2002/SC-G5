import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict
import time

def enrich_buildings_with_addresses(all_buildings, BAG_API_KEY):
    """
    Fetches and consolidates addresses for each building in all_buildings using the BAG API.

    Args:
        all_buildings (list): List of building dicts from BAG API.
        BAG_API_KEY (str): API key for BAG Individuele Bevragingen.

    Returns:
        dict: {pand_id: {'address': str, 'aantal_adressen': int}}
    """
    addresses_url = "https://api.bag.kadaster.nl/lvbag/individuelebevragingen/v2/adressen"
    session = requests.Session()
    session.headers.update({
        "X-Api-Key": BAG_API_KEY,
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

    def fetch_addresses_for_building(pand_id):
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
                    if response.status_code == 200:
                        data = response.json()
                        if '_embedded' in data and 'adressen' in data['_embedded']:
                            page_addresses = data['_embedded']['adressen']
                            addresses.extend(page_addresses)
                            if len(page_addresses) < 100:
                                return pand_id, addresses
                            page += 1
                            break
                        else:
                            return pand_id, addresses
                    elif response.status_code == 404:
                        return pand_id, []
                    else:
                        if attempt < max_retries - 1:
                            time.sleep(0.3)
                            continue
                        else:
                            return pand_id, []
                except Exception:
                    if attempt < max_retries - 1:
                        time.sleep(0.3)
                        continue
                    else:
                        return pand_id, []
            else:
                break
        return pand_id, addresses

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
    with ThreadPoolExecutor(max_workers=2) as executor:
        future_to_building = {executor.submit(fetch_addresses_for_building, bid): bid for bid in building_ids}
        for future in as_completed(future_to_building):
            pand_id, raw_addresses = future.result()
            consolidated_address = consolidate_addresses(raw_addresses)
            building_addresses[pand_id] = {
                'address': consolidated_address,
                'aantal_adressen': len(raw_addresses)
            }

    return building_addresses