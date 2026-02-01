"""
Exporter Module

Functions for exporting network DataFrames to CSV files.
"""

import os
import pandas as pd


def export_network_csvs(output_folder, warmtenet_links_carriers, nodes_techs, 
                        nodes_coordinates, links_techs, links_LQ_heat, 
                        links_electricity, links_costs):
    """
    Export all network DataFrames to CSV files.
    
    Parameters:
    -----------
    output_folder : str
        Folder to save output CSV files
    warmtenet_links_carriers : pd.DataFrame
        Warmtenet link carriers
    nodes_techs : pd.DataFrame
        All node technology assignments
    nodes_coordinates : pd.DataFrame
        All node coordinates
    links_techs : pd.DataFrame
        All link technical specifications
    links_LQ_heat : pd.DataFrame
        LQ heat link carriers
    links_electricity : pd.DataFrame
        Electricity link carriers
    links_costs : pd.DataFrame
        Link cost parameters
    
    Side Effects:
    -------------
    Creates output_folder if it doesn't exist and saves 7 CSV files.
    """
    os.makedirs(output_folder, exist_ok=True)
    
    warmtenet_links_carriers.to_csv(
        os.path.join(output_folder, 'warmtenet_links_carriers.csv'), index=False
    )
    nodes_techs.to_csv(
        os.path.join(output_folder, 'nodes_techs.csv'), index=False
    )
    nodes_coordinates.to_csv(
        os.path.join(output_folder, 'nodes_coordinates.csv'), index=False
    )
    links_techs.to_csv(
        os.path.join(output_folder, 'links_techs.csv'), index=False
    )
    links_LQ_heat.to_csv(
        os.path.join(output_folder, 'links_LQ_heat.csv'), index=False
    )
    links_electricity.to_csv(
        os.path.join(output_folder, 'links_electricity.csv'), index=False
    )
    links_costs.to_csv(
        os.path.join(output_folder, 'links_costs.csv'), index=False
    )
