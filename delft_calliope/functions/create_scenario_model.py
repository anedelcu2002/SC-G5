from time import time
import pandas as pd
import calliope
from ruamel.yaml import YAML
import os
import shutil
import time

def create_scenario_model(
    scenario,
    data_tables_folder='data_tables',
    base_yaml='inputs/calliope_model_config.yaml',
    tech_efficiencies=None,
    neighborhood_id=None
):
    """
    Create and configure a Calliope model based on scenario type by modifying CSV files and YAML.
    
    Parameters:
    -----------
    scenario : str
        'district_heating', 'full_electrification', or 'hybrid'
    data_tables_folder : str, optional
        Folder containing network CSV files (default: 'data_tables')
    base_yaml : str, optional
        Path to base YAML configuration (default: 'inputs/calliope_model_config.yaml')
    tech_efficiencies : dict, optional
        Technology efficiency parameters:
        - 'heat_pump_cop': Heat pump coefficient of performance (default: 4.0)
        - 'heat_substation_eff': Heat substation efficiency (default: 1.0)
    neighborhood_id : str, optional
        Neighborhood identifier for substation naming

    
    Returns:
    --------
    calliope.Model
        Configured Calliope model ready for building/solving
    
    Side Effects:
    -------------
    - Creates temporary YAML file in data_tables folder
    - Modifies CSV files in data_tables_folder based on scenario
    
    Notes:
    ------
    District heating scenario:
        - Deactivates electricity distribution links and nodes
        - Keeps heat distribution network active
    
    Full electrification scenario:
        - Deactivates heat distribution links and nodes
        - Adds heat pump technology to all demand nodes
        - Keeps electricity distribution network active
    
    Hybrid scenario:
        - Large buildings (≥threshold kW): Use district heating
        - Small buildings (<threshold kW): Use heat pumps
        - Keeps both transmission networks active
        - Selectively removes secondary links based on building size
    """
    if tech_efficiencies is None:
        tech_efficiencies = {
            'heat_pump_cop': 4.0,
            'heat_substation_eff': 1.0
        }
        
    #print(f"Configuring scenario: {scenario}")
    
    # Get the directory where this script is located
    script_dir = os.path.dirname(os.path.abspath(__file__))
    # Get the parent directory (delft_calliope)
    project_dir = os.path.dirname(script_dir)
    
    # Resolve paths relative to project directory
    base_yaml_path = os.path.join(project_dir, base_yaml)
    data_tables_path = os.path.join(project_dir, data_tables_folder)
    
    # Create temporary YAML file path in data_tables folder
    temp_yaml_path = os.path.join(data_tables_path, f'{scenario}_config.yaml')
    
    # Copy config YAML to temporary file
    shutil.copy2(base_yaml_path, temp_yaml_path)
    #print(f"   Copied {base_yaml_path} to {temp_yaml_path}")
    
    # Load the YAML for modifications
    yaml = YAML()
    with open(temp_yaml_path, 'r') as f:
        model_config = yaml.load(f)

    if 'data_tables' in model_config:
        for table_name, table_config in model_config['data_tables'].items():
            if isinstance(table_config, dict) and 'data' in table_config:
                # Replace 'data_tables/' with './' since YAML is now in data_tables folder
                if isinstance(table_config['data'], str):
                    table_config['data'] = table_config['data'].replace('data_tables/', './')
            elif isinstance(table_config, list):
                for item in table_config:
                    if isinstance(item, dict) and 'data' in item:
                        if isinstance(item['data'], str):
                            item['data'] = item['data'].replace('data_tables/', './')


        # Apply technology efficiencies to YAML
    if 'techs' in model_config:
        # Update heat pump efficiency
        if 'heat_pump' in model_config['techs']:
            model_config['techs']['heat_pump']['flow_out_eff'] = tech_efficiencies.get('heat_pump_cop', 4.0)
        
        # Update heat substation efficiency
        if 'heat_substation' in model_config['techs']:
            model_config['techs']['heat_substation']['flow_out_eff'] = tech_efficiencies.get('heat_substation_eff', 1.0)
        
        # Geothermal remains as supply tech without efficiency parameter (100% by default)
    
    # Read CSV files from data_tables folder
    nodes_techs = pd.read_csv(os.path.join(data_tables_path, 'nodes_techs.csv'))
    nodes_coordinates = pd.read_csv(os.path.join(data_tables_path, 'nodes_coordinates.csv'))
    links_techs = pd.read_csv(os.path.join(data_tables_path, 'links_techs.csv'))
    links_LQ_heat = pd.read_csv(os.path.join(data_tables_path, 'links_LQ_heat.csv'))
    links_electricity = pd.read_csv(os.path.join(data_tables_path, 'links_electricity.csv'))
    links_costs = pd.read_csv(os.path.join(data_tables_path, 'links_costs.csv'))
    
    if scenario == 'full_electrification':
        #print(" Configuring full electrification scenario...")
        
        # 1. Get demand nodes from coordinates file
        demand_nodes = nodes_coordinates[nodes_coordinates['nodes'].str.startswith('D')]['nodes']
        #print(f"   Found {len(demand_nodes)} demand nodes")
        
        # 2. Modify YAML to add heat pumps to demand nodes
        # Create top-level 'nodes' key if it doesn't exist
        if 'nodes' not in model_config:
            model_config['nodes'] = {}
        
        # Add heat pump technology to each demand node
        for node_name in demand_nodes:
            if node_name not in model_config['nodes']:
                model_config['nodes'][node_name] = {}
            if 'techs' not in model_config['nodes'][node_name]:
                model_config['nodes'][node_name]['techs'] = {}
            model_config['nodes'][node_name]['techs']['heat_pump'] = {}
        #print(f"   Added heat pumps to {len(demand_nodes)} demand nodes in YAML")

        
        # 3. Deactivate district heating links
        links_techs = links_techs[~links_techs['name'].str.contains("LQ heat distribution", na=False)].reset_index(drop=True)
        links_LQ_heat = links_LQ_heat[~links_LQ_heat['techs'].str.endswith('_heat')].reset_index(drop=True)
        links_costs = links_costs[~links_costs['techs'].str.endswith('_heat')].reset_index(drop=True)
        #print(f"   Deactivated heat distribution links")
        
        # 4. Deactivate heat transmission nodes
        nodes_techs = nodes_techs[~nodes_techs['nodes'].str.startswith('LQHtransmission')].reset_index(drop=True)
        nodes_coordinates = nodes_coordinates[~nodes_coordinates['nodes'].str.startswith('LQHtransmission')].reset_index(drop=True)
        #print(f"   Deactivated heat transmission nodes")
        
        # 5. Save modified CSV files
        links_techs.to_csv(os.path.join(data_tables_path, 'links_techs.csv'), index=False)
        links_LQ_heat.to_csv(os.path.join(data_tables_path, 'links_LQ_heat.csv'), index=False)
        links_costs.to_csv(os.path.join(data_tables_path, 'links_costs.csv'), index=False)
        nodes_techs.to_csv(os.path.join(data_tables_path, 'nodes_techs.csv'), index=False)
        nodes_coordinates.to_csv(os.path.join(data_tables_path, 'nodes_coordinates.csv'), index=False)
        #print(f"   Saved modified CSV files to {data_tables_path}/")
        
    elif scenario == 'district_heating':
        #print(" Configuring district heating scenario...")

        # Add substation node configuration
        if neighborhood_id is not None:
            substation_name = f"substation_{neighborhood_id}"
            if 'nodes' not in model_config:
                model_config['nodes'] = {}
            if substation_name not in model_config['nodes']:
                model_config['nodes'][substation_name] = {}
            if 'techs' not in model_config['nodes'][substation_name]:
                model_config['nodes'][substation_name]['techs'] = {}
            model_config['nodes'][substation_name]['techs']['heat_substation'] = {}
            #print(f"   Added heat_substation tech to {substation_name} node in YAML")
        
        # 1. Deactivate electricity distribution links
        links_techs = links_techs[~links_techs['name'].str.contains("LV electricity distribution", na=False)].reset_index(drop=True)
        links_electricity = links_electricity[~links_electricity['techs'].str.endswith('_electricity')].reset_index(drop=True)
        links_costs = links_costs[~links_costs['techs'].str.endswith('_electricity')].reset_index(drop=True)
        #print(f"   Deactivated electricity distribution links")
        
        # 2. Deactivate electricity transmission nodes
        nodes_techs = nodes_techs[~nodes_techs['nodes'].str.startswith('LVEtransmission')].reset_index(drop=True)
        nodes_coordinates = nodes_coordinates[~nodes_coordinates['nodes'].str.startswith('LVEtransmission')].reset_index(drop=True)
        #print(f"   Deactivated electricity transmission nodes")
        
        # 3. Save modified CSV files
        links_techs.to_csv(os.path.join(data_tables_path, 'links_techs.csv'), index=False)
        links_electricity.to_csv(os.path.join(data_tables_path, 'links_electricity.csv'), index=False)
        links_costs.to_csv(os.path.join(data_tables_path, 'links_costs.csv'), index=False)
        nodes_techs.to_csv(os.path.join(data_tables_path, 'nodes_techs.csv'), index=False)
        nodes_coordinates.to_csv(os.path.join(data_tables_path, 'nodes_coordinates.csv'), index=False)
        #print(f"   Saved modified CSV files to {data_tables_path}/")
    elif scenario == 'hybrid':
        #print(" Configuring hybrid scenario...")
        
        # Get demand threshold from tech_efficiencies
        demand_threshold_kW = tech_efficiencies.get('hybrid_threshold_kW', 50)
        #print(f"   Using demand threshold: {demand_threshold_kW} kW")
        
        # Get demand nodes with their heat demand values
        demand_techs = nodes_techs[
            (nodes_techs['techs'] == 'demand_LQ_heat') & 
            (nodes_techs['nodes'].str.startswith('D'))
        ].copy()
        
        # Classify buildings by demand
        large_buildings_mask = demand_techs['2050/01/01 00:00'] >= demand_threshold_kW
        small_buildings_mask = demand_techs['2050/01/01 00:00'] < demand_threshold_kW
        
        large_buildings = demand_techs[large_buildings_mask]['nodes'].values
        small_buildings = demand_techs[small_buildings_mask]['nodes'].values
        
        #print(f"   Large buildings (≥{demand_threshold_kW} kW): {len(large_buildings)}")
        #print(f"   Small buildings (<{demand_threshold_kW} kW): {len(small_buildings)}")
        
        # 1. Add heat pumps to small buildings in YAML
        if 'nodes' not in model_config:
            model_config['nodes'] = {}
        
        for node_name in small_buildings:
            if node_name not in model_config['nodes']:
                model_config['nodes'][node_name] = {}
            if 'techs' not in model_config['nodes'][node_name]:
                model_config['nodes'][node_name]['techs'] = {}
            model_config['nodes'][node_name]['techs']['heat_pump'] = {}
        #print(f"   Added heat pumps to {len(small_buildings)} small buildings in YAML")
        
        # Add substation node configuration if specified
        if neighborhood_id is not None:
            substation_name = f"substation_{neighborhood_id}"
            if substation_name not in model_config['nodes']:
                model_config['nodes'][substation_name] = {}
            if 'techs' not in model_config['nodes'][substation_name]:
                model_config['nodes'][substation_name]['techs'] = {}
            model_config['nodes'][substation_name]['techs']['heat_substation'] = {}
            #print(f"   Added heat_substation tech to {substation_name} node in YAML")
        
        # 2. Remove electricity secondary links for large buildings (they use district heating)
        if len(large_buildings) > 0:
            # Create pattern to match links starting with large building nodes
            large_building_patterns = [f"^{node}_to_.*_electricity$" for node in large_buildings]
            pattern = '|'.join(large_building_patterns)
            
            links_electricity = links_electricity[~links_electricity['techs'].str.match(pattern, na=False)].reset_index(drop=True)
            links_costs = links_costs[~links_costs['techs'].str.match(pattern, na=False)].reset_index(drop=True)
            #print(f"   Removed electricity links for {len(large_buildings)} large buildings")
        
        # 3. Remove heat secondary links for small buildings (they use heat pumps)
        if len(small_buildings) > 0:
            # Create pattern to match links starting with small building nodes
            small_building_patterns = [f"^{node}_to_.*_heat$" for node in small_buildings]
            pattern = '|'.join(small_building_patterns)
            
            links_LQ_heat = links_LQ_heat[~links_LQ_heat['techs'].str.match(pattern, na=False)].reset_index(drop=True)
            links_costs = links_costs[~links_costs['techs'].str.match(pattern, na=False)].reset_index(drop=True)
            #print(f"   Removed heat links for {len(small_buildings)} small buildings")
        
        # 4. Keep both transmission networks intact (don't delete transmission nodes/links)
        # No deletion of transmission nodes - both networks stay active
        
        # 5. Save modified CSV files
        links_techs.to_csv(os.path.join(data_tables_path, 'links_techs.csv'), index=False)
        links_LQ_heat.to_csv(os.path.join(data_tables_path, 'links_LQ_heat.csv'), index=False)
        links_electricity.to_csv(os.path.join(data_tables_path, 'links_electricity.csv'), index=False)
        links_costs.to_csv(os.path.join(data_tables_path, 'links_costs.csv'), index=False)
        nodes_techs.to_csv(os.path.join(data_tables_path, 'nodes_techs.csv'), index=False)
        nodes_coordinates.to_csv(os.path.join(data_tables_path, 'nodes_coordinates.csv'), index=False)
        #print(f"   Saved modified CSV files to {data_tables_path}/")
    else:
        raise ValueError(f"Unknown scenario '{scenario}'. Must be 'district_heating', 'full_electrification', or 'hybrid'.")
    
    # Write modified YAML
    with open(temp_yaml_path, 'w') as f:
        yaml.dump(model_config, f)
    #print(f"   Saved modified YAML to {temp_yaml_path}")
    
    # Load and return model from temporary YAML
    model = calliope.read_yaml(temp_yaml_path)
    #print(f"   Loaded Calliope model from {temp_yaml_path}")
    #print(f" Scenario '{scenario}' configured successfully")
    
    return model