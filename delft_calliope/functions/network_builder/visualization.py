"""
Visualization Module

Functions for creating network visualizations using Folium.
"""

import os
import folium


def create_network_map(nodes_coordinates, links_techs, debug_folder):
    """
    Generate an interactive Folium map of the network.
    
    Parameters:
    -----------
    nodes_coordinates : pd.DataFrame
        All node coordinates with columns ['nodes', 'latitude', 'longitude']
    links_techs : pd.DataFrame
        All link technical specifications
    debug_folder : str
        Folder to save the map HTML file
    
    Side Effects:
    -------------
    Saves network visualization to debug_folder/calliope_map.html
    """
    
    def is_valid_coord(val):
        try:
            float(val)
            return True
        except (TypeError, ValueError):
            return False
    
    # Prepare node coordinates DataFrame
    node_coords = nodes_coordinates.set_index('nodes')
    
    # Prepare links DataFrame - extract link_from and link_to if not present
    links_techs_viz = links_techs.copy()
    if 'link_from' not in links_techs_viz.columns or 'link_to' not in links_techs_viz.columns:
        links_techs_viz[['link_from', 'link_to']] = links_techs_viz['techs'].str.extract(r'^(.*?)_to_(.*?)_')
    
    # Create Folium map centered on mean coordinates
    center_lat = node_coords['latitude'].mean()
    center_lon = node_coords['longitude'].mean()
    network_map = folium.Map(location=[center_lat, center_lon], zoom_start=15, tiles='OpenStreetMap')
    
    # Create FeatureGroups for heat and electricity links
    heat_links_group = folium.FeatureGroup(name="Heat Links", show=True)
    elec_links_group = folium.FeatureGroup(name="Electricity Links", show=True)
    
    # Add nodes as circle markers
    for node, row in node_coords.iterrows():
        folium.CircleMarker(
            location=[row['latitude'], row['longitude']],
            radius=4,
            color='red',
            fill=True,
            fill_color='red',
            fill_opacity=0.7,
            popup=f"Node: {node}"
        ).add_to(network_map)
    
    # Add links as lines, separated by type
    for _, link in links_techs_viz.iterrows():
        from_node = link['link_from']
        to_node = link['link_to']
        
        if from_node in node_coords.index and to_node in node_coords.index:
            from_lat = node_coords.loc[from_node, 'latitude']
            from_lon = node_coords.loc[from_node, 'longitude']
            to_lat = node_coords.loc[to_node, 'latitude']
            to_lon = node_coords.loc[to_node, 'longitude']
            
            if all(is_valid_coord(x) for x in [from_lat, from_lon, to_lat, to_lon]):
                link_name = link.get('name', '')
                
                if "LQ heat distribution" in link_name:
                    folium.PolyLine(
                        locations=[[from_lat, from_lon], [to_lat, to_lon]],
                        color='#ff5100',
                        weight=2,
                        opacity=0.7,
                        popup=f"{from_node}  {to_node}"
                    ).add_to(heat_links_group)
                elif "LV electricity distribution" in link_name:
                    folium.PolyLine(
                        locations=[[from_lat, from_lon], [to_lat, to_lon]],
                        color='#3186cc',
                        weight=2,
                        opacity=0.7,
                        popup=f"{from_node}  {to_node}"
                    ).add_to(elec_links_group)
    
    # Add groups to map and layer control
    heat_links_group.add_to(network_map)
    elec_links_group.add_to(network_map)
    folium.LayerControl().add_to(network_map)
    
    # Save the map
    os.makedirs(debug_folder, exist_ok=True)
    network_map.save(os.path.join(debug_folder, 'calliope_map.html'))
