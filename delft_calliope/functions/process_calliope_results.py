import pandas as pd
import numpy as np
import os
import folium
import geopandas as gpd

def process_calliope_results(
    model,
    buildings_gdf,
    mode='plot',
    output_folder='outputs',
    heat_capacity=4.19,
    density=1000,
    delta_T=25,
    flow_speed=0.62,
    distance_factors=None,
    pipe_sizing_method='class' 
):
    """
    Process Calliope model results, create visualizations, and export bill of materials.
    
    Parameters:
    -----------
    model : calliope.Model
        Solved Calliope model with results
    buildings_gdf : gpd.GeoDataFrame
        GeoDataFrame with building geometries and heat demand data (must contain 'id', 'Peak heat demand (kW)', and geometry columns)
    mode : str, optional
        Run mode: 'plot' to generate visualization, 'export' to skip visualization (default: 'plot')
    output_folder : str, optional
        Folder to save output files (default: 'outputs')
    heat_capacity : float, optional
        Heat capacity in kJ/kgK for pipe sizing (default: 4.19)
    density : float, optional
        Density in kg/m3 for pipe sizing (default: 1000)
    delta_T : float, optional
        Temperature difference in K for pipe sizing (default: 25)
    flow_speed : float, optional
        Flow speed in m/s for pipe sizing (default: 0.62)
    distance_factors : dict, optional
        Multiplication factors for distances by segment type (default: all 1.0)
        Keys: 'Heat transmission main', 'LQ heat distribution main', 
              'LQ heat distribution secondary', 'LV electricity distribution main',
              'LV electricity distribution secondary'
    pipe_sizing_method : str, optional
        Method for calculating pipe diameters (default: 'class')
        - 'class': Use maximum diameter within each segment type (all pipes of same type get same diameter)
        - 'individual': Round each pipe diameter individually to nearest 5mm
    
    Returns:
    --------
    pd.DataFrame
        Bill of materials DataFrame with capacity, distances, and pipe diameters
    
    Side Effects:
    -------------
    - If mode=='plot', saves system_map.html to output_folder/
    - Saves bill_of_materials.csv to output_folder/
    """
    
    #print("Processing Calliope model results...")

    # Default distance factors if not provided
    if distance_factors is None:
        distance_factors = {
            'Heat transmission main': 1.0,
            'LQ heat distribution main': 1.0,
            'LQ heat distribution secondary': 1.0,
            'LV electricity distribution main': 1.0,
            'LV electricity distribution secondary': 1.0
        }
    
    # --- 1. Extract coordinates and flow capacities from model ---
    df_coords = model.inputs[["latitude", "longitude"]].to_dataframe().reset_index()
    
    df_capacity = (
        model.results.flow_cap.where(model.inputs.base_tech == "transmission")
        .to_series()
        .where(lambda x: x != 0)
        .dropna()
        .to_frame("Flow capacity (kW)")
        .reset_index()
    )
    
    # Merge coordinates with capacity data
    df_capacity_coords = pd.merge(df_coords, df_capacity, left_on="nodes", right_on="nodes").sort_values(by=['techs'])
    
    # --- 2. Visualize results (if mode=='plot') ---
    if mode == 'plot':
        #print("Generating system map visualization...")
        
        # Extract link information from techs column
        df_links = df_capacity_coords.copy()
        
        # Split the techs column to get link_from and link_to
        df_links[['link_from', 'link_to_carrier']] = df_links['techs'].str.rsplit('_to_', n=1, expand=True)
        df_links['link_to'] = df_links['link_to_carrier'].str.replace(r'_(heat|electricity|HQ_heat|LQ_heat)$', '', regex=True)
        df_links['link_from'] = df_links['link_from'].str.replace(r'_(heat|electricity|HQ_heat|LQ_heat)$', '', regex=True)
        
        # Merge with df_coords twice to get both from and to coordinates
        df_links = df_links.merge(
            df_coords[['nodes', 'latitude', 'longitude']],
            left_on='link_from',
            right_on='nodes',
            how='left',
            suffixes=('', '_from')
        )
        df_links = df_links.rename(columns={'latitude': 'lat_from', 'longitude': 'lon_from'})
        
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
        
        # Create Folium map
        center_lat = df_coords['latitude'].mean()
        center_lon = df_coords['longitude'].mean()
        map_fig = folium.Map(
            location=[center_lat, center_lon],
            zoom_start=16,
            tiles='OpenStreetMap'
        )
        
        # Create FeatureGroups for different layers
        demand_group = folium.FeatureGroup(name="Demand Nodes", show=True).add_to(map_fig)
        supply_heat_group = folium.FeatureGroup(name="Supply Heat Nodes", show=True).add_to(map_fig)
        supply_elec_group = folium.FeatureGroup(name="Supply Electricity Nodes", show=True).add_to(map_fig)
        transmission_heat_group = folium.FeatureGroup(name="Heat Transmission Nodes", show=True).add_to(map_fig)
        distribution_heat_group = folium.FeatureGroup(name="Heat Distribution Nodes", show=True).add_to(map_fig)
        HQ_heat_link_group = folium.FeatureGroup(name="HQ Heat Links", show=True).add_to(map_fig)
        LQ_heat_link_group = folium.FeatureGroup(name="LQ Heat Links", show=True).add_to(map_fig)
        distribution_electricity_group = folium.FeatureGroup(name="Electricity Distribution Nodes", show=True).add_to(map_fig)
        electricity_link_group = folium.FeatureGroup(name="Electricity Links", show=True).add_to(map_fig)
        substation_group = folium.FeatureGroup(name="Substations", show=True).add_to(map_fig)
        building_group = folium.FeatureGroup(name="Buildings", show=True).add_to(map_fig)
        
        # Add link polylines
        for idx, row in df_links.iterrows():
            if row['carriers'] == 'HQ_heat':
                color = 'red'
                target_group = HQ_heat_link_group
                weight = 4
            elif row['carriers'] == 'LQ_heat':
                color = "#ff5100"
                target_group = LQ_heat_link_group
                weight = 2
            else:
                color = 'blue'
                target_group = electricity_link_group
                weight = 2
            
            folium.PolyLine(
                locations=[[row['lat_from'], row['lon_from']], [row['lat_to'], row['lon_to']]],
                color=color,
                weight=weight,
                opacity=1,
                popup=f"<b>{row['techs']}</b><br>From: {row['link_from']}<br>To: {row['link_to']}<br>Capacity: {row['Flow capacity (kW)']} kW"
            ).add_to(target_group)
        
        # Add node markers
        for idx, row in df_capacity_coords.iterrows():
            node_name = row['nodes']
            
            # Determine node type and styling
            if node_name.startswith('geothermie'):
                color = '#2ecc71'
                radius = 5
                node_type = 'Supply heat'
                target_group = supply_heat_group
            elif node_name.startswith('MV'):
                color = "#2e38cc"
                radius = 1
                node_type = 'Supply electricity'
                target_group = supply_elec_group
            elif node_name.startswith('D'):
                color = "#ff9100"
                radius = 3
                node_type = 'Demand'
                target_group = demand_group
            elif node_name.startswith('warmtenet'):
                color = "#94d3ae"
                radius = 1
                node_type = 'Transmission heat'
                target_group = transmission_heat_group
            elif node_name.startswith('LQHtransmission'):
                color = "#94d3ae"
                radius = 1
                node_type = 'Distribution heat'
                target_group = distribution_heat_group
            elif node_name.startswith('substation'):
                color = "#ff3300"
                radius = 3
                node_type = 'Heat substation'
                target_group = substation_group
            else:
                color = "#7076cc"
                radius = 1
                node_type = 'Distribution electricity'
                target_group = distribution_electricity_group
            
            folium.CircleMarker(
                location=[row['latitude'], row['longitude']],
                radius=radius,
                popup=f"<b>{row['nodes']}</b> ({node_type})<br>Capacity: {row['Flow capacity (kW)']} kW",
                color=color,
                fill=True,
                fillColor=color,
                fillOpacity=1,
                weight=2
            ).add_to(target_group)
        
        # Add building polygons with color based on heat demand
        # Convert buildings_gdf to WGS84 if not already
        if buildings_gdf.crs is not None and buildings_gdf.crs.to_string() != 'EPSG:4326':
            buildings_gdf_wgs84 = buildings_gdf.to_crs(epsg=4326)
        else:
            buildings_gdf_wgs84 = buildings_gdf
        
        max_demand = buildings_gdf['Peak heat demand (kW)'].max()
        min_demand = buildings_gdf['Peak heat demand (kW)'].min()
        
        for idx, row in buildings_gdf_wgs84.iterrows():
            demand = row['Peak heat demand (kW)']
            normalized = (demand - min_demand) / (max_demand - min_demand) if max_demand > min_demand else 0.5
            
            # Color from light yellow (low demand) to dark red (high demand)
            red = int(255)
            green = int(255 * (1 - normalized*0.9))
            blue = int(255 * (1 - normalized*0.9))
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

        # Add floating statistics box
        # Extract model size from summary
        num_nodes = int(len(model.inputs.coords.get('nodes', [])))
        num_techs = int(len(model.inputs.coords.get('techs', [])))
        num_carriers = int(len(model.inputs.coords.get('carriers', [])))
        num_timesteps = int(len(model.inputs.coords.get('timesteps', [])))
        num_links = int((model.inputs.base_tech == "transmission").sum()) if 'base_tech' in model.inputs else 0
        
        # Build statistics HTML
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
                <tr style="background-color: #f0f0f0;"><td colspan="2" style="padding: 5px; font-weight: bold;">Model Size</td></tr>
                <tr><td style="padding: 3px; padding-left: 10px;">Nodes:</td><td style="text-align: right; padding: 3px;">{num_nodes}</td></tr>
                <tr><td style="padding: 3px; padding-left: 10px;">Links:</td><td style="text-align: right; padding: 3px;">{num_links}</td></tr>
        """
        
        # Add results summary if model is solved
        if hasattr(model, 'results') and len(model.results.data_vars) > 0:
            try:
                stats_html += '<tr style="background-color: #f0f0f0;"><td colspan="2" style="padding: 5px; padding-top: 10px; font-weight: bold;">Results Summary</td></tr>'
                
                 # Initialize variables to track values for efficiency calculation
                geo_cap = 0.0
                hp_cap = 0.0
                heat_demand = 0.0

                # Supply geothermal capacity
                try:
                    geo_cap = float(model.results['flow_out'].sel(techs='supply_geothermal').sum())
                    stats_html += f'<tr><td style="padding: 3px; padding-left: 10px;">Supply Geothermal:</td><td style="text-align: right; padding: 3px;">{geo_cap:,.0f} kW</td></tr>'
                except (KeyError, ValueError):
                    stats_html += f'<tr><td style="padding: 3px; padding-left: 10px;">Supply Geothermal:</td><td style="text-align: right; padding: 3px;">0 kW</td></tr>'
                
                # Heat pump capacity
                try:
                    hp_cap = float(model.results['flow_out'].sel(techs='heat_pump').sum())
                    stats_html += f'<tr><td style="padding: 3px; padding-left: 10px;">Heat Pumps:</td><td style="text-align: right; padding: 3px;">{hp_cap:,.0f} kW</td></tr>'
                except (KeyError, ValueError):
                    stats_html += f'<tr><td style="padding: 3px; padding-left: 10px;">Heat Pumps:</td><td style="text-align: right; padding: 3px;">0 kW</td></tr>'
            
                # Total heat demand
                try:
                    heat_demand = abs(float(model.results['flow_in'].sel(techs='demand_LQ_heat').sum()))
                    stats_html += f'<tr><td style="padding: 3px; padding-left: 10px;">Total Heat Demand:</td><td style="text-align: right; padding: 3px;">{heat_demand:,.0f} kW</td></tr>'
                except (KeyError, ValueError):
                    stats_html += f'<tr><td style="padding: 3px; padding-left: 10px;">Total Heat Demand:</td><td style="text-align: right; padding: 3px;">0 kW</td></tr>'
            
                # District heating efficiency (only if heat pump = 0)
                if hp_cap == 0.0 and geo_cap > 0:
                    efficiency = heat_demand / geo_cap
                    stats_html += f'<tr><td style="padding: 3px; padding-left: 10px;">DH Efficiency:</td><td style="text-align: right; padding: 3px;">{efficiency:.3f}</td></tr>'
       
            except Exception:
                pass
        
        stats_html += """
            </table>
        </div>
        """
        
        map_fig.get_root().html.add_child(folium.Element(stats_html))

        # Add LayerControl
        folium.LayerControl().add_to(map_fig)
        
        # Save the map
        os.makedirs(output_folder, exist_ok=True)
        map_fig.save(os.path.join(output_folder, 'system_map.html'))
        #print(f" Saved system map to {output_folder}/system_map.html")
    
    # --- 3. Export bill of materials ---
    #print("Calculating bill of materials...")
    
    tech_names = model.inputs.name.to_series().dropna()
    tech_distances = model.inputs.distance.to_series().dropna()
    
    total_flow_out = (
        model.results.flow_out
        .sum(dim=["nodes", "carriers", "timesteps"], min_count=1)
        .to_series()
        .dropna()
    )
    
    export_df = pd.DataFrame({
        'name': tech_names,
        'capacity_kw': total_flow_out,
        'distance_m': tech_distances * 1000
    })
    
    # Apply distance multiplication factors
    export_df['distance_m'] = export_df.apply(
        lambda row: row['distance_m'] * distance_factors.get(row['name'], 1.0), 
        axis=1
    )
    # Calculate flow rates and pipe diameters (ONLY for heat segments)
    # Identify heat-related segments
    heat_segments = export_df['name'].str.contains('heat|Heat', case=False, na=False)
    
    export_df['flow_rate_m^3/s'] = np.where(
        heat_segments & export_df['capacity_kw'].notnull() & export_df['distance_m'].notnull(),
        export_df['capacity_kw'] / (heat_capacity * density * delta_T),
        np.nan
    )
    
    export_df['diameter_mm'] = np.where(
        heat_segments & export_df['capacity_kw'].notnull() & export_df['distance_m'].notnull(),
        (export_df['flow_rate_m^3/s'] / np.pi / flow_speed * 4)**0.5 * 1000,
        np.nan
    )
    
    # Round up to nearest 5mm for standard pipe sizes
    def round_up_to_5(x):
        return int(np.ceil(x / 5.0) * 5) if not np.isnan(x) else np.nan
    
    # Apply pipe sizing method (ONLY for heat segments)
    if pipe_sizing_method == 'class':
        # Class-based sizing: use maximum diameter for each heat segment type
        max_heat_transmission_main = round_up_to_5(
            export_df.loc[export_df['name'] == 'Heat transmission main', 'diameter_mm'].max()
        )
        max_lq_heat_distribution_main = round_up_to_5(
            export_df.loc[export_df['name'] == 'LQ heat distribution main', 'diameter_mm'].max()
        )
        max_lq_heat_distribution_secondary = round_up_to_5(
            export_df.loc[export_df['name'] == 'LQ heat distribution secondary', 'diameter_mm'].max()
        )
        
        export_df['final_diameter_mm'] = np.select(
            [
                export_df['name'] == 'Heat transmission main',
                export_df['name'] == 'LQ heat distribution main',
                export_df['name'] == 'LQ heat distribution secondary'
            ],
            [
                max_heat_transmission_main,
                max_lq_heat_distribution_main,
                max_lq_heat_distribution_secondary
            ],
            default=np.nan  # Electricity segments get NaN
        )
    
    elif pipe_sizing_method == 'individual':
        # Individual sizing: round each heat pipe diameter individually to nearest 5mm
        # Electricity segments remain NaN
        export_df['final_diameter_mm'] = np.where(
            heat_segments,
            export_df['diameter_mm'].apply(round_up_to_5),
            np.nan
        )
    
    else:
        raise ValueError(f"Invalid pipe_sizing_method '{pipe_sizing_method}'. Must be 'class' or 'individual'")
    
    export_df['name'] = export_df.apply(
        lambda row: f"{row['name']}_DN{int(row['final_diameter_mm'])}" 
                    if pd.notnull(row['final_diameter_mm']) 
                    else row['name'],
        axis=1
    )

    # Filter and sort
    final_export_df = export_df[export_df['capacity_kw'] > 0].sort_values(
        by=['name', 'capacity_kw'],
        ascending=[True, False]
    ).reset_index(drop=True)
    
    # Save to CSV
    os.makedirs(output_folder, exist_ok=True)
    final_export_df.to_csv(os.path.join(output_folder, 'bill_of_materials.csv'), index=False)
    #print(f" Saved bill of materials to {output_folder}/bill_of_materials.csv")
    
    return final_export_df
