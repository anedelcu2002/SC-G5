"""
Carrier and Cost Builder Module

Functions for creating link carrier and cost DataFrames.
"""

import pandas as pd


def create_link_carriers(links_techs, warmtenet_links_carriers):
    """
    Create carrier DataFrames for heat and electricity links.
    
    Parameters:
    -----------
    links_techs : pd.DataFrame
        All link technical specifications
    warmtenet_links_carriers : pd.DataFrame
        Base warmtenet link carriers (used as template)
    
    Returns:
    --------
    tuple
        (links_LQ_heat, links_electricity) DataFrames
    """
    # Create links_LQ_heat
    links_LQ_heat = warmtenet_links_carriers.iloc[0:0].copy()
    lq_heat_techs = links_techs.loc[
        links_techs['name'].str.contains("LQ heat distribution", na=False), 'techs'
    ]
    
    new_rows = pd.DataFrame(1, index=range(len(lq_heat_techs)), columns=links_LQ_heat.columns)
    new_rows['techs'] = lq_heat_techs.values
    links_LQ_heat = pd.concat([links_LQ_heat, new_rows], ignore_index=True)
    
    # Create links_electricity
    lv_elec_techs = links_techs.loc[
        links_techs['name'].str.contains("LV electricity distribution", na=False), 'techs'
    ]
    
    new_rows_elec = pd.DataFrame(1, index=range(len(lv_elec_techs)), columns=warmtenet_links_carriers.columns)
    new_rows_elec['techs'] = lv_elec_techs.values
    links_electricity = pd.concat([warmtenet_links_carriers.iloc[0:0].copy(), new_rows_elec], ignore_index=True)
    
    return links_LQ_heat, links_electricity


def create_link_costs(links_techs, cost_per_distance=100):
    """
    Create cost DataFrame for all links.
    
    Parameters:
    -----------
    links_techs : pd.DataFrame
        All link technical specifications
    cost_per_distance : float
        Cost per distance unit (default: 100)
    
    Returns:
    --------
    pd.DataFrame
        Link costs DataFrame
    """
    links_costs = pd.DataFrame({
        'techs': links_techs['techs'],
        'cost_flow_cap_per_distance': cost_per_distance
    })
    
    return links_costs


def add_emergency_links_to_carriers(links_LQ_heat, links_electricity, links_costs,
                                     emergency_links, cost_per_distance=100):
    """
    Add emergency links to carrier and cost DataFrames.
    
    Parameters:
    -----------
    links_LQ_heat : pd.DataFrame
        Existing LQ heat carriers
    links_electricity : pd.DataFrame
        Existing electricity carriers
    links_costs : pd.DataFrame
        Existing link costs
    emergency_links : list
        List of emergency link dictionaries
    cost_per_distance : float
        Cost per distance unit (default: 100)
    
    Returns:
    --------
    tuple
        (updated_links_LQ_heat, updated_links_electricity, updated_links_costs)
    """
    if not emergency_links:
        return links_LQ_heat, links_electricity, links_costs
    
    # Separate heat and electricity emergency links
    heat_emergency_links = [link for link in emergency_links if link['techs'].endswith('_heat')]
    elec_emergency_links = [link for link in emergency_links if link['techs'].endswith('_electricity')]
    
    # Add heat emergency links to carriers and costs
    if heat_emergency_links:
        emergency_lq_heat = pd.DataFrame({
            'techs': [link['techs'] for link in heat_emergency_links],
            'carrier_out': [1] * len(heat_emergency_links),
            'carrier_in': [1] * len(heat_emergency_links)
        })
        links_LQ_heat = pd.concat([links_LQ_heat, emergency_lq_heat], ignore_index=True)
        
        heat_emergency_costs = pd.DataFrame({
            'techs': [link['techs'] for link in heat_emergency_links],
            'cost_flow_cap_per_distance': [cost_per_distance] * len(heat_emergency_links)
        })
        links_costs = pd.concat([links_costs, heat_emergency_costs], ignore_index=True)
    
    # Add electricity emergency links to carriers and costs
    if elec_emergency_links:
        emergency_electricity = pd.DataFrame({
            'techs': [link['techs'] for link in elec_emergency_links],
            'carrier_out': [1] * len(elec_emergency_links),
            'carrier_in': [1] * len(elec_emergency_links)
        })
        links_electricity = pd.concat([links_electricity, emergency_electricity], ignore_index=True)
        
        elec_emergency_costs = pd.DataFrame({
            'techs': [link['techs'] for link in elec_emergency_links],
            'cost_flow_cap_per_distance': [cost_per_distance] * len(elec_emergency_links)
        })
        links_costs = pd.concat([links_costs, elec_emergency_costs], ignore_index=True)
    
    return links_LQ_heat, links_electricity, links_costs
