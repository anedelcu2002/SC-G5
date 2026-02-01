"""
Command Line Argument Parser for run_analysis.py

This module defines all command line arguments for the district heating
network analysis script.
"""

import argparse


DEFAULT_CONFIG_PATH = 'run_analysis_config.yaml'


def parse_arguments():
    """
    Parse command line arguments for run_analysis.py.
    
    Default values are set to None so that the YAML config file provides
    the base configuration, and CLI arguments can selectively override
    specific values.
    
    Returns
    -------
    argparse.Namespace
        Parsed command line arguments
    """
    parser = argparse.ArgumentParser(
        description='District Heating Network Analysis for Delft Neighborhoods'
    )
    
    # ==========================================================================
    # Configuration and scenario selection
    # ==========================================================================
    
    parser.add_argument(
        '--config', '-c',
        type=str,
        default=DEFAULT_CONFIG_PATH,
        help=f'Path to YAML configuration file (default: {DEFAULT_CONFIG_PATH})'
    )
    
    parser.add_argument(
        '--neighborhood',
        type=str,
        default=None,
        help="Neighborhood to analyze. Available: multatulibuurt, holstbuurt, mythologiebuurt, poptahofzuid"
    )
    
    parser.add_argument(
        '--year',
        type=int,
        default=None,
        help='Year for heat demand data. Available: 2013 (cold), 2019 (normal), 2020 (warm)'
    )
    
    parser.add_argument(
        '--scenario', 
        type=str,
        default=None,
        help="Scenario type: 'district_heating', 'full_electrification', or 'hybrid'"
    )
    
    parser.add_argument(
        '--threshold', 
        type=float,
        default=None,
        help="Demand threshold in kW for hybrid scenario (default: 50)"
    )
    
    parser.add_argument(
        '--topology_source',
        type=str,
        choices=['stedin', 'osm'],
        default=None,
        help="Network topology source: 'stedin' (grid data) or 'osm' (OpenStreetMap roads)"
    )
    
    # ==========================================================================
    # Execution settings
    # ==========================================================================
    
    parser.add_argument(
        '--mode',
        type=str,
        choices=['plot', 'export'],
        default=None,
        help='Run mode: plot generates visualizations, export skips them'
    )
    
    parser.add_argument(
        '--debug',
        action='store_true',
        help='Debug mode: use only one demand node for faster testing'
    )
    
    parser.add_argument(
        '--spacing',
        type=float,
        default=None,
        help='Node spacing in meters'
    )
    
    parser.add_argument(
        '--list-neighborhoods',
        action='store_true',
        help='List all available neighborhoods and exit'
    )
    
    # ==========================================================================
    # Data source settings
    # ==========================================================================
    
    parser.add_argument(
        '--online', 
        action='store_true',
        default=False,
        help='Fetch data from APIs instead of using cached files (requires --bag-api-key)'
    )
    
    parser.add_argument(
        '--bag-api-key',
        type=str,
        default=None,
        help='BAG API key for online mode (obtain from https://www.kadaster.nl/zakelijk/producten/adressen-en-gebouwen/bag-api)'
    )
    
    # ==========================================================================
    # Output paths
    # ==========================================================================
    
    parser.add_argument(
        '--output-folder',
        type=str,
        default=None,
        help="Output folder for results"
    )
    
    parser.add_argument(
        '--data-tables-folder',
        type=str,
        default=None,
        help="Data tables folder for intermediate CSV files"
    )
    
    parser.add_argument(
        '--debug-folder',
        type=str,
        default=None,
        help='Debug folder for visualizations'
    )
    
    # ==========================================================================
    # Technology efficiency parameters
    # ==========================================================================
    
    parser.add_argument(
        '--heat-pump-cop',
        type=float,
        default=None,
        help='Heat pump coefficient of performance'
    )
    
    parser.add_argument(
        '--heat-substation-eff',
        type=float,
        default=None,
        help='Heat substation efficiency'
    )
    
    # ==========================================================================
    # Pipe sizing parameters
    # ==========================================================================
    
    parser.add_argument(
        '--pipe-sizing',
        type=str,
        choices=['class', 'individual'],
        default=None,
        help="Pipe sizing method: 'class' (uniform per type) or 'individual' (per pipe)"
    )
    
    parser.add_argument(
        '--delta-t',
        type=float,
        default=None,
        help='Temperature difference for pipe sizing in °C'
    )
    
    parser.add_argument(
        '--flow-speed',
        type=float,
        default=None,
        help='Flow speed for pipe sizing in m/s'
    )
    
    # ==========================================================================
    # Distance factors
    # ==========================================================================
    
    parser.add_argument(
        '--distance-factor-heat-trans-main',
        type=float,
        default=None,
        help='Distance factor for heat transmission main'
    )
    
    parser.add_argument(
        '--distance-factor-heat-dist-main',
        type=float,
        default=None,
        help='Distance factor for LQ heat distribution main'
    )
    
    parser.add_argument(
        '--distance-factor-heat-dist-sec',
        type=float,
        default=None,
        help='Distance factor for LQ heat distribution secondary'
    )
    
    parser.add_argument(
        '--distance-factor-elec-dist-main',
        type=float,
        default=None,
        help='Distance factor for LV electricity distribution main'
    )
    
    parser.add_argument(
        '--distance-factor-elec-dist-sec',
        type=float,
        default=None,
        help='Distance factor for LV electricity distribution secondary'
    )
    
    # ==========================================================================
    # Heat loss rates
    # ==========================================================================
    
    parser.add_argument(
        '--heat-loss-rate-trans-main',
        type=float,
        default=None,
        help='Heat loss rate for heat transmission main in W/m'
    )
    
    parser.add_argument(
        '--heat-loss-rate-dist-main',
        type=float,
        default=None,
        help='Heat loss rate for LQ heat distribution main in W/m'
    )
    
    parser.add_argument(
        '--heat-loss-rate-dist-sec',
        type=float,
        default=None,
        help='Heat loss rate for LQ heat distribution secondary in W/m'
    )
    
    parser.add_argument(
        '--apply-heat-losses',
        type=lambda x: x.lower() == 'true',
        default=None,
        help='Apply heat transmission losses (true/false)'
    )
    
    # ==========================================================================
    # Electricity resistance rates
    # ==========================================================================
    
    parser.add_argument(
        '--elec-resistance-main',
        type=float,
        default=None,
        help='Electricity resistance for LV distribution main in Ω/km'
    )
    
    parser.add_argument(
        '--elec-resistance-sec',
        type=float,
        default=None,
        help='Electricity resistance for LV distribution secondary in Ω/km'
    )
    
    parser.add_argument(
        '--apply-electricity-losses',
        type=lambda x: x.lower() == 'true',
        default=None,
        help='Apply electricity transmission losses (true/false)'
    )
    
    return parser.parse_args()
