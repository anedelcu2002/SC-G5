import pandas as pd
import calliope
from ruamel.yaml import YAML
import os

def create_scenario_model(
    scenario,
    data_tables_folder='data_tables',
    base_yaml_district='district_heating_model.yaml',
    base_yaml_electrification='electrification_model.yaml'
):
    """
    Create and configure a Calliope model based on scenario type by modifying CSV files.
    
    Parameters:
    -----------
    scenario : str
        'district_heating' or 'full_electrification'
    data_tables_folder : str, optional
        Folder containing network CSV files (default: 'data_tables')
    base_yaml_district : str, optional
        Path to district heating YAML configuration (default: 'district_heating_model.yaml')
    base_yaml_electrification : str, optional
        Path to electrification YAML configuration (default: 'electrification_model.yaml')
    
    Returns:
    --------
    calliope.Model
        Configured Calliope model ready for building/solving
    
    Side Effects:
    -------------
    - Modifies CSV files in data_tables_folder based on scenario
    - For full_electrification: creates modified YAML with heat pumps added to demand nodes
    
    Notes:
    ------
    District heating scenario:
        - Deactivates electricity distribution links and nodes
        - Keeps heat distribution network active
    
    Full electrification scenario:
        - Deactivates heat distribution links and nodes
        - Adds heat pump technology to all demand nodes
        - Keeps electricity distribution network active
    """
    
    #print(f"Configuring scenario: {scenario}")
    
    # Read CSV files from data_tables folder
    nodes_techs = pd.read_csv(os.path.join(data_tables_folder, 'nodes_techs.csv'))
    nodes_coordinates = pd.read_csv(os.path.join(data_tables_folder, 'nodes_coordinates.csv'))
    links_techs = pd.read_csv(os.path.join(data_tables_folder, 'links_techs.csv'))
    links_LQ_heat = pd.read_csv(os.path.join(data_tables_folder, 'links_LQ_heat.csv'))
    links_electricity = pd.read_csv(os.path.join(data_tables_folder, 'links_electricity.csv'))
    links_costs = pd.read_csv(os.path.join(data_tables_folder, 'links_costs.csv'))
    
    if scenario == 'full_electrification':
        #print(" Configuring full electrification scenario...")
        
        # 1. Get demand nodes from coordinates file
        demand_nodes = nodes_coordinates[nodes_coordinates['nodes'].str.startswith('D')]['nodes']
        #print(f"   Found {len(demand_nodes)} demand nodes")
        
        # 2. Modify YAML to add heat pumps to demand nodes
        yaml = YAML()
        with open(base_yaml_district, 'r') as f:
            model_config = yaml.load(f)
        
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
        
        # Write modified YAML
        with open(base_yaml_electrification, 'w') as f:
            yaml.dump(model_config, f)
        #print(f"   Created {base_yaml_electrification} with heat pumps")
        
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
        links_techs.to_csv(os.path.join(data_tables_folder, 'links_techs.csv'), index=False)
        links_LQ_heat.to_csv(os.path.join(data_tables_folder, 'links_LQ_heat.csv'), index=False)
        links_costs.to_csv(os.path.join(data_tables_folder, 'links_costs.csv'), index=False)
        nodes_techs.to_csv(os.path.join(data_tables_folder, 'nodes_techs.csv'), index=False)
        nodes_coordinates.to_csv(os.path.join(data_tables_folder, 'nodes_coordinates.csv'), index=False)
        #print(f"   Saved modified CSV files to {data_tables_folder}/")
        
        # 6. Load and return model
        model = calliope.read_yaml(base_yaml_electrification)
        #print(f"   Loaded Calliope model from {base_yaml_electrification}")
        
    elif scenario == 'district_heating':
        #print(" Configuring district heating scenario...")
        
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
        links_techs.to_csv(os.path.join(data_tables_folder, 'links_techs.csv'), index=False)
        links_electricity.to_csv(os.path.join(data_tables_folder, 'links_electricity.csv'), index=False)
        links_costs.to_csv(os.path.join(data_tables_folder, 'links_costs.csv'), index=False)
        nodes_techs.to_csv(os.path.join(data_tables_folder, 'nodes_techs.csv'), index=False)
        nodes_coordinates.to_csv(os.path.join(data_tables_folder, 'nodes_coordinates.csv'), index=False)
        #print(f"   Saved modified CSV files to {data_tables_folder}/")
        
        # 4. Load and return model
        model = calliope.read_yaml(base_yaml_district)
        #print(f"   Loaded Calliope model from {base_yaml_district}")
        
    else:
        raise ValueError(f"Unknown scenario '{scenario}'. Must be 'district_heating' or 'full_electrification'")
    
    #print(f" Scenario '{scenario}' configured successfully")
    return model
