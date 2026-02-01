# SC-G5: Delft Heat Transition Infrastructure Model

A Calliope-based energy system model for analyzing heating infrastructure alternatives in Delft neighborhoods. This tool estimates system capacity, network topology, and outputs a bill of materials for district heating and electrification scenarios. The outcomes of the model are integrated with full life cycle analysis (LCA) results to calculate the environmental impact of each infrastructure alternative.

📄 **Full methodology**: See [Environmental Impacts of Infrastructure for the Delft Heat Transition.pdf](Environmental%20Impacts%20of%20Infrastructure%20for%20the%20Delft%20Heat%20Transition.pdf)

## Overview

The model is formulated as a linear optimizer using the open-source [Calliope](https://doi.org/10.21105/joss.00825) energy system modeling framework (v0.7.0). It calculates the minimum system capacity required to satisfy a neighborhood's peak heat demand while minimizing infrastructure costs. It allows for three heating scenarios (district heating, full electrification, and hybrid), four neighborhoods (Multatulibuurt, Roland Holstbuurt, Mythologiebuurt, and Poptahof-Zuid), two network topologies (Stedin grid data or Openstreetmap street network), three weather scenarios (cold, normal, warm), and various variations of input parameters.

For any questions or feedback, please contact anedelcu2002@gmail.com.

## Installation

### Prerequisites

- **Python 3.9 - 3.11** (Calliope 0.7.0 compatibility)
- **[Gurobi](https://www.gurobi.com/) solver** - Free academic license available at [gurobi.com/academia](https://www.gurobi.com/academia/academic-program-and-licenses/)

### Dependencies

Install all required packages:

```bash
conda create -n delft-calliope python=3.11
conda activate delft-calliope
conda install -c conda-forge calliope=0.7.0 pandas numpy geopandas folium shapely pyproj networkx requests ruamel.yaml pyyaml pyrosm
```

- BAG API key from [Kadaster](https://www.kadaster.nl/zakelijk/producten/adressen-en-gebouwen/bag-api)

## Quick Start

```bash
cd delft_calliope

# Run with default settings (uses run_analysis_config.yaml)
python run_analysis.py

# List available neighborhoods
python run_analysis.py --list-neighborhoods

# Run specific scenario
python run_analysis.py --neighborhood holstbuurt --year 2019 --scenario full_electrification

# Fast mode without visualizations
python run_analysis.py --mode export

# Debug mode (single demand node for testing)
python run_analysis.py --debug
```

### Parallel/Batch Execution

```bash
# Run multiple scenarios in parallel
python run_parallel.py

# With custom config
python run_parallel.py --config run_parallel_config.yaml
```

## Configuration

### Single Run (`run_analysis_config.yaml`)

```yaml
scenario:
  neighborhood: multatulibuurt    # multatulibuurt, holstbuurt, mythologiebuurt, poptahofzuid
  year: 2019                      # 2013 (cold), 2019 (normal), 2020 (warm)
  type: district_heating          # district_heating, full_electrification, hybrid
  topology_source: stedin         # stedin (grid data) or osm (street network)

execution:
  mode: plot                      # plot (with maps) or export (faster)
  debug_single_node: false
  spacing_m: 5                    # Transmission node spacing in meters

tech_efficiencies:
  heat_pump_cop: 4.0              # Air-to-air heat pump COP
  heat_substation_eff: 0.9        # District heating substation efficiency
```

### Batch Run (`run_parallel_config.yaml`)

Configure multiple neighborhoods, years, scenarios, and parameter ranges for sensitivity analysis.


## Outputs

### Single Run
- `scenario_summary.json` - Comprehensive results including capacities, losses, execution time
- `bill_of_materials.csv` - Network components with lengths and pipe diameters
- `system_map.html` - Interactive Folium map of the network

### Batch Run
- `scenario_summary.csv` - Aggregated results from all scenarios
- `execution_summary.json` - Run metadata and status
- Individual scenario folders with full outputs

## Contributors

Model development: Alex Nedelcu
LCA files and integration: Elvire Landais, Daan van Amelsfort, Zhi-Chin Ju
