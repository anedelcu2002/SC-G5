"""
System Map Visualization

Functions for creating Folium maps visualizing the energy system network,
including nodes, links, buildings, and statistics overlays.
"""

import os
import folium


def create_system_map(
    df_capacity_coords,
    df_coords,
    buildings_gdf,
    model,
    adjusted_capacities,
    supply_losses,
    unmet_demand_by_node,
    loss_statistics,
    output_folder,
    apply_heat_losses=False,
    apply_electricity_losses=False
):
    """
    Generate and save a Folium map visualizing the energy system.
    
    Parameters
    ----------
    df_capacity_coords : pandas.DataFrame
        DataFrame with flow capacities and coordinates.
    df_coords : pandas.DataFrame
        DataFrame with node coordinates.
    buildings_gdf : geopandas.GeoDataFrame
        GeoDataFrame with building geometries and heat demand.
    model : calliope.Model
        Solved Calliope model.
    adjusted_capacities : dict
        Dictionary of tech -> adjusted capacity after loss calculations.
    supply_losses : dict
        Dictionary of supply_node -> additional kW needed for losses.
    unmet_demand_by_node : dict
        Dictionary of node -> unmet demand in kW.
    loss_statistics : dict
        Dictionary with loss statistics for display.
    output_folder : str
        Folder to save the map HTML file.
    apply_heat_losses : bool, optional
        Whether heat losses were calculated (affects display).
    apply_electricity_losses : bool, optional
        Whether electricity losses were calculated (affects display).
    """
    # Extract link information
    df_links = _prepare_link_data(df_capacity_coords, df_coords)
    
    # Create base map
    center_lat = df_coords['latitude'].mean()
    center_lon = df_coords['longitude'].mean()
    map_fig = folium.Map(
        location=[center_lat, center_lon],
        zoom_start=16,
        tiles='OpenStreetMap'
    )
    
    # Create feature groups for layers
    groups = _create_feature_groups(map_fig)
    
    # Add link polylines
    _add_link_polylines(
        map_fig, df_links, groups, adjusted_capacities, apply_heat_losses
    )
    
    # Add node markers
    _add_node_markers(
        map_fig, df_capacity_coords, groups, supply_losses, 
        unmet_demand_by_node, apply_heat_losses
    )
    
    # Add building polygons
    _add_building_polygons(map_fig, buildings_gdf, groups['building_group'])
    
    # Add statistics overlay
    _add_statistics_overlay(
        map_fig, model, loss_statistics, supply_losses,
        unmet_demand_by_node, apply_heat_losses, apply_electricity_losses
    )
    
    # Add layer control
    folium.LayerControl().add_to(map_fig)
    
    # Save map
    os.makedirs(output_folder, exist_ok=True)
    map_fig.save(os.path.join(output_folder, 'system_map.html'))


def _prepare_link_data(df_capacity_coords, df_coords):
    """Prepare link data with from/to coordinates."""
    df_links = df_capacity_coords.copy()
    
    # Split techs column to get link endpoints
    df_links[['link_from', 'link_to_carrier']] = df_links['techs'].str.rsplit(
        '_to_', n=1, expand=True
    )
    df_links['link_to'] = df_links['link_to_carrier'].str.replace(
        r'_(heat|electricity|HQ_heat|LQ_heat)$', '', regex=True
    )
    df_links['link_from'] = df_links['link_from'].str.replace(
        r'_(heat|electricity|HQ_heat|LQ_heat)$', '', regex=True
    )
    
    # Merge coordinates for 'from' endpoint
    df_links = df_links.merge(
        df_coords[['nodes', 'latitude', 'longitude']],
        left_on='link_from',
        right_on='nodes',
        how='left',
        suffixes=('', '_from')
    )
    df_links = df_links.rename(columns={'latitude': 'lat_from', 'longitude': 'lon_from'})
    
    # Merge coordinates for 'to' endpoint
    df_links = df_links.merge(
        df_coords[['nodes', 'latitude', 'longitude']],
        left_on='link_to',
        right_on='nodes',
        how='left',
        suffixes=('_temp', '_to')
    )
    df_links = df_links.rename(columns={'latitude': 'lat_to', 'longitude': 'lon_to'})
    
    # Clean up duplicate columns
    df_links = df_links.drop(columns=['nodes_temp', 'nodes_to'], errors='ignore')
    
    return df_links


def _create_feature_groups(map_fig):
    """Create and add feature groups for different layers."""
    groups = {
        'demand_group': folium.FeatureGroup(name="Demand Nodes", show=True),
        'unmet_demand_group': folium.FeatureGroup(name="Unmet Demand Nodes", show=True),
        'supply_heat_group': folium.FeatureGroup(name="Supply Heat Nodes", show=True),
        'supply_elec_group': folium.FeatureGroup(name="Supply Electricity Nodes", show=True),
        'transmission_heat_group': folium.FeatureGroup(name="Heat Transmission Nodes", show=True),
        'distribution_heat_group': folium.FeatureGroup(name="Heat Distribution Nodes", show=True),
        'HQ_heat_link_group': folium.FeatureGroup(name="HQ Heat Links", show=True),
        'LQ_heat_link_group': folium.FeatureGroup(name="LQ Heat Links", show=True),
        'distribution_electricity_group': folium.FeatureGroup(name="Electricity Distribution Nodes", show=True),
        'electricity_link_group': folium.FeatureGroup(name="Electricity Links", show=True),
        'substation_group': folium.FeatureGroup(name="Substations", show=True),
        'building_group': folium.FeatureGroup(name="Buildings", show=True),
    }
    
    for group in groups.values():
        group.add_to(map_fig)
    
    return groups


def _add_link_polylines(map_fig, df_links, groups, adjusted_capacities, apply_heat_losses):
    """Add polylines for network links."""
    for idx, row in df_links.iterrows():
        if row['carriers'] == 'HQ_heat':
            color = 'red'
            target_group = groups['HQ_heat_link_group']
            weight = 4
        elif row['carriers'] == 'LQ_heat':
            color = "#ff5100"
            target_group = groups['LQ_heat_link_group']
            weight = 2
        else:
            color = 'blue'
            target_group = groups['electricity_link_group']
            weight = 2
        
        # Get capacity values
        tech_key = row['techs']
        original_capacity = row['Flow capacity (kW)']
        adjusted_capacity = adjusted_capacities.get(tech_key, original_capacity) if apply_heat_losses else original_capacity
        loss = adjusted_capacity - original_capacity if apply_heat_losses else 0.0
        
        # Build popup
        popup_text = f"<b>{row['techs']}</b><br>From: {row['link_from']}<br>To: {row['link_to']}<br>"
        if apply_heat_losses and loss > 0:
            popup_text += f"Original Capacity: {original_capacity:.2f} kW<br>"
            popup_text += f"<b>Adjusted Capacity: {adjusted_capacity:.2f} kW</b><br>"
            popup_text += f"Loss: +{loss:.2f} kW"
        else:
            popup_text += f"Capacity: {original_capacity:.2f} kW"
        
        folium.PolyLine(
            locations=[[row['lat_from'], row['lon_from']], [row['lat_to'], row['lon_to']]],
            color=color,
            weight=weight,
            opacity=1,
            popup=popup_text
        ).add_to(target_group)


def _add_node_markers(map_fig, df_capacity_coords, groups, supply_losses,
                      unmet_demand_by_node, apply_heat_losses):
    """Add circle markers for network nodes."""
    for idx, row in df_capacity_coords.iterrows():
        node_name = row['nodes']
        original_capacity = row['Flow capacity (kW)']
        
        # Calculate adjusted capacity for supply nodes
        if apply_heat_losses and node_name in supply_losses:
            adjusted_capacity = original_capacity + supply_losses[node_name]
            loss = supply_losses[node_name]
        else:
            adjusted_capacity = original_capacity
            loss = 0.0
        
        has_unmet_demand = node_name in unmet_demand_by_node
        
        # Determine node styling
        style = _get_node_style(node_name, has_unmet_demand)
        target_group = groups[style['group_key']]
        
        # Build popup
        popup_text = f"<b>{row['nodes']}</b> ({style['node_type']})<br>"
        if has_unmet_demand:
            unmet_value = unmet_demand_by_node[node_name]
            popup_text += f"<b style='color: red;'>Unmet Demand: {unmet_value:.2f} kW</b><br>"
        if apply_heat_losses and loss > 0:
            popup_text += f"Original Capacity: {original_capacity:.2f} kW<br>"
            popup_text += f"<b>Adjusted Capacity: {adjusted_capacity:.2f} kW</b><br>"
            popup_text += f"Additional supply for losses: +{loss:.2f} kW"
        else:
            popup_text += f"Capacity: {original_capacity:.2f} kW"
        
        folium.CircleMarker(
            location=[row['latitude'], row['longitude']],
            radius=style['radius'],
            popup=popup_text,
            color=style['color'],
            fill=True,
            fillColor=style['color'],
            fillOpacity=1,
            weight=2
        ).add_to(target_group)


def _get_node_style(node_name, has_unmet_demand):
    """Determine styling for a node based on its name."""
    if node_name.startswith('geothermie'):
        return {'color': '#2ecc71', 'radius': 5, 'node_type': 'Supply heat', 
                'group_key': 'supply_heat_group'}
    elif node_name.startswith('MV'):
        return {'color': '#2e38cc', 'radius': 1, 'node_type': 'Supply electricity',
                'group_key': 'supply_elec_group'}
    elif node_name.startswith('D'):
        if has_unmet_demand:
            return {'color': '#ff0000', 'radius': 4, 'node_type': 'Demand (UNMET)',
                    'group_key': 'unmet_demand_group'}
        else:
            return {'color': '#ff9100', 'radius': 3, 'node_type': 'Demand',
                    'group_key': 'demand_group'}
    elif node_name.startswith('warmtenet'):
        return {'color': '#94d3ae', 'radius': 1, 'node_type': 'Transmission heat',
                'group_key': 'transmission_heat_group'}
    elif node_name.startswith('LQHtransmission'):
        return {'color': '#94d3ae', 'radius': 1, 'node_type': 'Distribution heat',
                'group_key': 'distribution_heat_group'}
    elif node_name.startswith('substation'):
        return {'color': '#ff3300', 'radius': 3, 'node_type': 'Heat substation',
                'group_key': 'substation_group'}
    else:
        return {'color': '#7076cc', 'radius': 1, 'node_type': 'Distribution electricity',
                'group_key': 'distribution_electricity_group'}


def _add_building_polygons(map_fig, buildings_gdf, building_group):
    """Add building polygons colored by heat demand."""
    # Convert to WGS84 if needed
    if buildings_gdf.crs is not None and buildings_gdf.crs.to_string() != 'EPSG:4326':
        buildings_gdf_wgs84 = buildings_gdf.to_crs(epsg=4326)
    else:
        buildings_gdf_wgs84 = buildings_gdf
    
    max_demand = buildings_gdf['Peak heat demand (kW)'].max()
    min_demand = buildings_gdf['Peak heat demand (kW)'].min()
    
    for idx, row in buildings_gdf_wgs84.iterrows():
        demand = row['Peak heat demand (kW)']
        normalized = (demand - min_demand) / (max_demand - min_demand) if max_demand > min_demand else 0.5
        
        # Color gradient from light yellow to dark red
        red = int(255)
        green = int(255 * (1 - normalized * 0.9))
        blue = int(255 * (1 - normalized * 0.9))
        color = f'#{red:02x}{green:02x}{blue:02x}'
        
        folium.GeoJson(
            row.geometry,
            style_function=lambda x, color=color: {
                'fillColor': color,
                'color': '#333333',
                'weight': 1,
                'fillOpacity': 0.8
            },
            popup=folium.Popup(
                f"<b>Building ID:</b> {row['id']}<br>"
                f"<b>Peak Heat Demand:</b> {row['Peak heat demand (kW)']:.2f} kW<br>",
                max_width=250
            )
        ).add_to(building_group)


def _add_statistics_overlay(map_fig, model, loss_statistics, supply_losses,
                            unmet_demand_by_node, apply_heat_losses, apply_electricity_losses):
    """Add floating statistics box to the map."""
    # Extract model size
    num_nodes = int(len(model.inputs.coords.get('nodes', [])))
    num_links = int((model.inputs.base_tech == "transmission").sum()) if 'base_tech' in model.inputs else 0
    
    stats_html = f"""
    <div style="position: fixed; 
                bottom: 10px; 
                left: 10px; 
                width: 300px; 
                background-color: white; 
                border: 2px solid grey; 
                border-radius: 5px;
                z-index: 9999; 
                font-size: 12px;
                padding: 10px;
                box-shadow: 0 0 10px rgba(0,0,0,0.3);">
        <h4 style="margin: 0 0 10px 0; color: #333;">Model Statistics</h4>
        <table style="width: 100%; border-collapse: collapse;">
            <tr style="background-color: #f0f0f0;">
                <td colspan="2" style="padding: 5px; font-weight: bold;">Model Size</td>
            </tr>
            <tr>
                <td style="padding: 3px; padding-left: 10px;">Nodes:</td>
                <td style="text-align: right; padding: 3px;">{num_nodes}</td>
            </tr>
            <tr>
                <td style="padding: 3px; padding-left: 10px;">Links:</td>
                <td style="text-align: right; padding: 3px;">{num_links}</td>
            </tr>
    """
    
    # Add results summary if model is solved
    if hasattr(model, 'results') and len(model.results.data_vars) > 0:
        stats_html += _build_results_summary_html(
            model, loss_statistics, supply_losses, unmet_demand_by_node,
            apply_heat_losses, apply_electricity_losses
        )
    
    stats_html += """
        </table>
    </div>
    """
    
    map_fig.get_root().html.add_child(folium.Element(stats_html))


def _build_results_summary_html(model, loss_statistics, supply_losses, unmet_demand_by_node,
                                 apply_heat_losses, apply_electricity_losses):
    """Build HTML for results summary section."""
    html = '<tr style="background-color: #f0f0f0;"><td colspan="2" style="padding: 5px; padding-top: 10px; font-weight: bold;">Results Summary</td></tr>'
    
    geo_cap_original = 0.0
    geo_cap_adjusted = 0.0
    hp_cap = 0.0
    heat_demand = 0.0
    
    # Supply geothermal capacity
    try:
        geo_cap_original = float(model.results['flow_out'].sel(techs='supply_geothermal').sum())
        
        if apply_heat_losses and 'geothermie_delft' in supply_losses:
            geo_cap_adjusted = geo_cap_original + supply_losses['geothermie_delft']
            html += f'<tr><td style="padding: 3px; padding-left: 10px;">Supply Geothermal:</td><td style="text-align: right; padding: 3px;"><b>{geo_cap_adjusted:,.0f} kW</b></td></tr>'
            html += f'<tr><td style="padding: 3px; padding-left: 20px; font-size: 10px; color: #666;">Original:</td><td style="text-align: right; padding: 3px; font-size: 10px; color: #666;">{geo_cap_original:,.0f} kW</td></tr>'
            html += f'<tr><td style="padding: 3px; padding-left: 20px; font-size: 10px; color: #666;">Losses:</td><td style="text-align: right; padding: 3px; font-size: 10px; color: #666;">+{supply_losses["geothermie_delft"]:,.0f} kW</td></tr>'
        else:
            geo_cap_adjusted = geo_cap_original
            html += f'<tr><td style="padding: 3px; padding-left: 10px;">Supply Geothermal:</td><td style="text-align: right; padding: 3px;">{geo_cap_original:,.0f} kW</td></tr>'
    except (KeyError, ValueError):
        html += '<tr><td style="padding: 3px; padding-left: 10px;">Supply Geothermal:</td><td style="text-align: right; padding: 3px;">0 kW</td></tr>'
    
    # Heat pump capacity
    try:
        hp_cap = float(model.results['flow_out'].sel(techs='heat_pump').sum())
        html += f'<tr><td style="padding: 3px; padding-left: 10px;">Heat Pumps:</td><td style="text-align: right; padding: 3px;">{hp_cap:,.0f} kW</td></tr>'
    except (KeyError, ValueError):
        html += '<tr><td style="padding: 3px; padding-left: 10px;">Heat Pumps:</td><td style="text-align: right; padding: 3px;">0 kW</td></tr>'
    
    # Total heat demand
    try:
        heat_demand = abs(float(model.results['flow_in'].sel(techs='demand_LQ_heat').sum()))
        html += f'<tr><td style="padding: 3px; padding-left: 10px;">Total Heat Demand:</td><td style="text-align: right; padding: 3px;">{heat_demand:,.0f} kW</td></tr>'
    except (KeyError, ValueError):
        html += '<tr><td style="padding: 3px; padding-left: 10px;">Total Heat Demand:</td><td style="text-align: right; padding: 3px;">0 kW</td></tr>'
    
    # Heat loss information
    if apply_heat_losses and loss_statistics.get('total_system_losses_kw', 0) > 0:
        total_system_losses = loss_statistics['total_system_losses_kw']
        total_LQ_losses = loss_statistics.get('total_LQ_losses_kw', 0)
        total_HQ_losses = loss_statistics.get('total_HQ_losses_kw', 0)
        substation_losses = loss_statistics.get('substation_efficiency_losses_kw', 0)
        
        html += '<tr style="background-color: #fff3cd;"><td colspan="2" style="padding: 5px; padding-top: 10px; font-weight: bold;">Heat System Losses</td></tr>'
        html += f'<tr><td style="padding: 3px; padding-left: 10px;">Total Heat Losses:</td><td style="text-align: right; padding: 3px;"><b>{total_system_losses:,.2f} kW</b></td></tr>'
        
        if substation_losses > 0:
            html += f'<tr><td style="padding: 3px; padding-left: 20px; font-size: 10px; color: #666;">Pipe losses:</td><td style="text-align: right; padding: 3px; font-size: 10px; color: #666;">{total_LQ_losses + total_HQ_losses:,.2f} kW</td></tr>'
            html += f'<tr><td style="padding: 3px; padding-left: 20px; font-size: 10px; color: #666;">Substation losses:</td><td style="text-align: right; padding: 3px; font-size: 10px; color: #666;">{substation_losses:,.2f} kW</td></tr>'
        
        is_hybrid = hp_cap > 0 and geo_cap_original > 0
        if heat_demand > 0 and not is_hybrid:
            loss_percentage = (total_system_losses / heat_demand) * 100
            html += f'<tr><td style="padding: 3px; padding-left: 10px;">Loss Percentage:</td><td style="text-align: right; padding: 3px;">{loss_percentage:.1f}%</td></tr>'
    
    # District heating efficiency
    if hp_cap == 0.0 and geo_cap_adjusted > 0:
        efficiency = heat_demand / geo_cap_adjusted
        html += f'<tr><td style="padding: 3px; padding-left: 10px;">DH Efficiency:</td><td style="text-align: right; padding: 3px;">{efficiency:.3f}</td></tr>'
    
    # Electricity loss information
    if apply_electricity_losses and loss_statistics.get('total_LV_losses_kw', 0) > 0:
        total_LV_losses = loss_statistics['total_LV_losses_kw']
        html += '<tr style="background-color: #cce5ff;"><td colspan="2" style="padding: 5px; padding-top: 10px; font-weight: bold;">Electricity Transmission Losses</td></tr>'
        html += f'<tr><td style="padding: 3px; padding-left: 10px;">Total LV Losses:</td><td style="text-align: right; padding: 3px;"><b>{total_LV_losses:,.2f} kW</b></td></tr>'
    
    # Unmet demand information
    total_unmet = sum(unmet_demand_by_node.values())
    if total_unmet > 0:
        num_unmet = sum(1 for n in unmet_demand_by_node if n.startswith('D'))
        all_nodes = model.inputs.coords['nodes'].values
        total_demand_nodes = sum(1 for n in all_nodes if str(n).startswith('D'))
        
        html += '<tr style="background-color: #ffcccc;"><td colspan="2" style="padding: 5px; padding-top: 10px; font-weight: bold;">Unmet Demand</td></tr>'
        html += f'<tr><td style="padding: 3px; padding-left: 10px;">Total Unmet Demand:</td><td style="text-align: right; padding: 3px;"><b>{total_unmet:,.0f}/{heat_demand:,.0f} kW</b></td></tr>'
        html += f'<tr><td style="padding: 3px; padding-left: 10px;">Nodes with Unmet Demand:</td><td style="text-align: right; padding: 3px;"><b>{num_unmet}/{total_demand_nodes}</b></td></tr>'
        
        if heat_demand > 0:
            unmet_percentage = (total_unmet / heat_demand) * 100
            html += f'<tr><td style="padding: 3px; padding-left: 10px;">Unmet Demand %:</td><td style="text-align: right; padding: 3px;">{unmet_percentage:.1f}%</td></tr>'
    
    return html
