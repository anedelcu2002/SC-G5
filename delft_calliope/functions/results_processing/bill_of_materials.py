"""
Bill of Materials Export

Functions for calculating pipe diameters, applying distance factors,
and exporting the bill of materials to CSV.
"""

import os
import numpy as np
import pandas as pd

from functions.results_processing.extract_model_data import get_tech_metadata


def export_bill_of_materials(
    model,
    adjusted_capacities,
    supply_losses,
    distance_factors,
    output_folder,
    pipe_sizing_params=None,
    pipe_sizing_method='class',
    apply_losses=False
):
    """
    Calculate pipe diameters and export bill of materials to CSV.
    
    Parameters
    ----------
    model : calliope.Model
        Solved Calliope model.
    adjusted_capacities : dict
        Dictionary of tech -> adjusted capacity after loss calculations.
    supply_losses : dict
        Dictionary of supply_node -> additional kW needed for losses.
    distance_factors : dict
        Multiplication factors for distances by segment type.
    output_folder : str
        Folder to save the CSV file.
    pipe_sizing_params : dict, optional
        Parameters for pipe sizing calculation:
        - heat_capacity: kJ/kgK (default: 4.19)
        - density: kg/m³ (default: 1000)
        - delta_T: K (default: 25)
        - flow_speed: m/s (default: 0.62)
    pipe_sizing_method : str, optional
        Method for calculating pipe diameters (default: 'class'):
        - 'class': Use maximum diameter within each segment type
        - 'individual': Round each pipe diameter individually to nearest 5mm
    apply_losses : bool, optional
        Whether loss adjustments should be applied (default: False).
    
    Returns
    -------
    pandas.DataFrame
        Bill of materials DataFrame with capacity, distances, and pipe diameters.
    """
    # Default pipe sizing parameters
    if pipe_sizing_params is None:
        pipe_sizing_params = {}
    
    heat_capacity = pipe_sizing_params.get('heat_capacity', 4.19)
    density = pipe_sizing_params.get('density', 1000)
    delta_T = pipe_sizing_params.get('delta_T', 25)
    flow_speed = pipe_sizing_params.get('flow_speed', 0.62)
    
    # Get technology metadata
    tech_names, tech_distances = get_tech_metadata(model)
    
    # Get total flow out
    total_flow_out = (
        model.results.flow_out
        .sum(dim=["nodes", "carriers", "timesteps"], min_count=1)
        .to_series()
        .dropna()
    )
    
    # Apply adjusted capacities if losses were calculated
    if apply_losses and len(adjusted_capacities) > 0:
        total_flow_out = _apply_capacity_adjustments(
            total_flow_out, adjusted_capacities, supply_losses
        )
    
    # Build export DataFrame
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
    
    # Calculate pipe diameters for heat segments
    export_df = _calculate_pipe_diameters(
        export_df, heat_capacity, density, delta_T, flow_speed, pipe_sizing_method
    )
    
    # Filter and sort
    final_export_df = export_df[export_df['capacity_kw'] > 0].sort_values(
        by=['name', 'capacity_kw'],
        ascending=[True, False]
    ).reset_index(drop=True)
    
    # Save to CSV
    os.makedirs(output_folder, exist_ok=True)
    final_export_df.to_csv(os.path.join(output_folder, 'bill_of_materials.csv'), index=False)
    
    return export_df


def _apply_capacity_adjustments(total_flow_out, adjusted_capacities, supply_losses):
    """
    Apply loss adjustments to flow capacities.
    
    Parameters
    ----------
    total_flow_out : pandas.Series
        Original flow out values indexed by tech.
    adjusted_capacities : dict
        Adjusted capacities for transmission links.
    supply_losses : dict
        Additional capacity needed for supply nodes.
    
    Returns
    -------
    pandas.Series
        Updated flow out values.
    """
    # Update transmission link capacities
    for tech_idx in total_flow_out.index:
        if tech_idx in adjusted_capacities:
            total_flow_out[tech_idx] = adjusted_capacities[tech_idx]
    
    # Track which techs have been updated to avoid duplicates
    updated_techs = set()
    
    # Update supply node capacities
    for supply_node, loss_kw in supply_losses.items():
        matched_techs = _find_matching_supply_techs(total_flow_out.index, supply_node)
        
        if not matched_techs:
            continue
        
        # For transformers, aggregate all losses and apply once
        if 'transformer' in supply_node.lower():
            if matched_techs[0] not in updated_techs:
                total_transformer_losses = sum(
                    loss for node, loss in supply_losses.items()
                    if 'transformer' in node.lower()
                )
                total_flow_out[matched_techs[0]] += total_transformer_losses
                updated_techs.add(matched_techs[0])
        else:
            # For non-transformer supplies, apply individual losses
            for tech_idx in matched_techs:
                if tech_idx not in updated_techs:
                    total_flow_out[tech_idx] += loss_kw
                    updated_techs.add(tech_idx)
    
    # Update substation capacities
    for key, total_demand in adjusted_capacities.items():
        if key.startswith('_substation_adjustment_'):
            for tech_idx in total_flow_out.index:
                tech_str = str(tech_idx).lower()
                if 'substation' in tech_str and ('conversion' in tech_str or 'hq' in tech_str or 'lq' in tech_str):
                    total_flow_out[tech_idx] = total_demand
                    break
    
    return total_flow_out


def _find_matching_supply_techs(tech_indices, supply_node):
    """
    Find technologies matching a supply node.
    
    Parameters
    ----------
    tech_indices : pandas.Index
        Index of technology identifiers.
    supply_node : str
        Supply node name to match.
    
    Returns
    -------
    list
        List of matching technology identifiers.
    """
    matched_techs = []
    supply_lower = supply_node.lower()
    
    for tech_idx in tech_indices:
        tech_str = str(tech_idx).lower()
        
        if 'transformer' in supply_lower or 'trafo' in supply_lower:
            if (('low-voltage' in tech_str or 'low voltage' in tech_str or 'lv' in tech_str) and
                'electricity' in tech_str and 'supply' in tech_str):
                matched_techs.append(tech_idx)
        
        elif 'geotherm' in supply_lower:
            if 'geothermal' in tech_str and 'supply' in tech_str:
                matched_techs.append(tech_idx)
        
        elif 'substation' in supply_lower:
            if 'substation' in tech_str and ('conversion' in tech_str or 'hq' in tech_str or 'lq' in tech_str):
                matched_techs.append(tech_idx)
    
    return matched_techs


def _calculate_pipe_diameters(export_df, heat_capacity, density, delta_T, flow_speed, method):
    """
    Calculate pipe diameters for heat segments.
    
    Parameters
    ----------
    export_df : pandas.DataFrame
        DataFrame with capacity and distance data.
    heat_capacity : float
        Heat capacity in kJ/kgK.
    density : float
        Density in kg/m³.
    delta_T : float
        Temperature difference in K.
    flow_speed : float
        Flow speed in m/s.
    method : str
        Sizing method: 'class' or 'individual'.
    
    Returns
    -------
    pandas.DataFrame
        DataFrame with added diameter columns.
    """
    # Identify heat segments
    heat_segments = export_df['name'].str.contains('heat|Heat', case=False, na=False)
    
    # Calculate flow rates (only for heat segments)
    export_df['flow_rate_m^3/s'] = np.where(
        heat_segments & export_df['capacity_kw'].notnull() & export_df['distance_m'].notnull(),
        export_df['capacity_kw'] / (heat_capacity * density * delta_T),
        np.nan
    )
    
    # Calculate raw diameters
    export_df['diameter_mm'] = np.where(
        heat_segments & export_df['capacity_kw'].notnull() & export_df['distance_m'].notnull(),
        (export_df['flow_rate_m^3/s'] / np.pi / flow_speed * 4) ** 0.5 * 1000,
        np.nan
    )
    
    # Round up to nearest 5mm
    def round_up_to_5(x):
        return int(np.ceil(x / 5.0) * 5) if not np.isnan(x) else np.nan
    
    # Apply sizing method
    if method == 'class':
        # Use maximum diameter for each heat segment type
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
            default=np.nan
        )
    
    elif method == 'individual':
        # Round each pipe diameter individually
        export_df['final_diameter_mm'] = np.where(
            heat_segments,
            export_df['diameter_mm'].apply(round_up_to_5),
            np.nan
        )
    
    else:
        raise ValueError(f"Invalid pipe_sizing_method '{method}'. Must be 'class' or 'individual'")
    
    # Append diameter to name for heat segments
    export_df['name'] = export_df.apply(
        lambda row: f"{row['name']}_DN{int(row['final_diameter_mm'])}"
                    if pd.notnull(row['final_diameter_mm'])
                    else row['name'],
        axis=1
    )
    
    return export_df
