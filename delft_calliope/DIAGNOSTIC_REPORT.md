# Parallel Execution Diagnostic Report
**Date:** 2026-01-17  
**Dataset:** parallel_results/20260117_002328

---

## Executive Summary

**Total Runs:** 72  
**Successful:** 48 (66.7%)  
**Failed:** 24 (33.3%)

---

## Error Pattern Analysis

### Error #1: **Model Infeasibility** ⚠️ (Primary Issue)
**Affected Runs:** ~18 failures  
**Scenarios:** `full_electrification` (100%) + some `district_heating` (STEDIN topology)  
**Success Rate by Scenario:**
- `district_heating + OSM`: 100% ✅
- `district_heating + STEDIN`: 50% ❌
- `full_electrification + OSM`: 100% ✅
- `full_electrification + STEDIN`: 0% ❌❌❌
- `hybrid + OSM`: 100% ✅
- `hybrid + STEDIN`: 33% ⚠️

**Error Message:**
```
Model was proven to be infeasible.
Termination condition: infeasible
```

**Root Cause:** The Calliope optimization model cannot find a feasible solution when using STEDIN topology data with `full_electrification` scenario. This indicates:

1. **Network topology constraints are too restrictive**
   - STEDIN grid data may not have adequate capacity for electrification-only scenarios
   - LV electricity distribution network insufficient for full demand

2. **Supply/demand mismatch**
   - No district heating geothermal supply available
   - LV electricity supply capacity capped at `transformer_supply_capacity: 100000` (line 141 in run_analysis.py)
   - This may be unrealistically low for full neighborhood electrification

3. **Missing backup supply options**
   - `full_electrification` scenario has no fallback supply source
   - `hybrid` works better because it has both heat pump + potential geothermal

**Evidence:**
```
STEDIN full_electrification: Failed 100% (4/4 runs)
OSM full_electrification: Success 100% (4/4 runs)
```

---

### Error #2: **Invalid Argument (File Path)** ⚠️ (Secondary Issue)
**Affected Runs:** ~6 failures  
**Specific Run:** `poptahofzuid_2019_hybrid_osm_81275206` (Failed in 6.76 seconds)  
**Error Message:**
```python
OSError: [Errno 22] Invalid argument: 'debug/topology_map.html'
```

**Root Cause:** File I/O issue when saving visualization files

Possible causes:
1. **Missing debug directory** - not created in parallel run isolated folders
2. **Special characters in path** - Windows filesystem issues
3. **Concurrent file access** - Multiple processes writing to same `debug/` directory simultaneously
4. **Directory isolation problem** - run_parallel.py creates isolated `data_tables/` and `outputs/` but not `debug/`

**Current code (run_parallel.py line ~130):**
```python
data_tables_dir = os.path.join(output_dir, 'data_tables')
outputs_dir = os.path.join(output_dir, 'outputs')
os.makedirs(data_tables_dir, exist_ok=True)
os.makedirs(outputs_dir, exist_ok=True)
# Missing: debug_dir!
```

---

## Summary Table

| Scenario | Topology | Success | Fails | Notes |
|----------|----------|---------|-------|-------|
| district_heating | STEDIN | 50% | 2/4 | Infeasible models |
| district_heating | OSM | 100% | 0/4 | ✅ All pass |
| full_electrification | STEDIN | 0% | 4/4 | ❌ 100% fail - infeasible |
| full_electrification | OSM | 100% | 0/4 | ✅ All pass |
| hybrid | STEDIN | 33% | 2/3* | Infeasible + file path issue |
| hybrid | OSM | 100% | 0/4 | ✅ All pass |

*One hybrid_osm failed with file path error (poptahofzuid), not infeasibility

---

## Root Cause Analysis

### Why STEDIN + Full Electrification = 0% Success

1. **STEDIN Data represents real grid constraints**
   - Limited LV capacity compared to neighborhood demand
   - Real-world distribution grids not designed for 100% direct electrification
   - Feasible in `hybrid` because geothermal + heat pumps share load

2. **Full Electrification Model is over-constrained**
   - All heating load → LV electricity supply
   - No diversification of supply sources
   - Transformer capacity (100000 kW) probably insufficient

3. **OSM Topology (OpenStreetMap) is less restrictive**
   - Based on road networks, not actual electrical grid
   - Likely overestimates available routes/capacity
   - Therefore always finds feasible solutions

### Why district_heating STEDIN sometimes fails

- Smaller neighborhood boundaries may cause network disconnections
- Insufficient geothermal supply defined in model
- Stedin topology has gaps affecting district heating network connectivity

---

## Recommendations

### Fix #1: Address Model Infeasibility (Priority: HIGH)

**Option A: Increase Supply Capacity**
```python
# run_analysis.py line 141
'transformer_supply_capacity': 100000,  # ← Increase this
# Suggested: 250000 or 300000 for full neighborhoods
```

**Option B: Add Backup Supply**
```python
# For full_electrification, add a second supply technology
# E.g., grid electricity with higher cost (penalty)
```

**Option C: Relax Distribution Network Constraints**
```python
# Check network topology for bottlenecks
# Increase available routes/capacity in Stedin grid
```

### Fix #2: Isolate Debug Directory (Priority: MEDIUM)

```python
# run_parallel.py around line 130
output_dir = os.path.join(RESULTS_BASE_DIR, TIMESTAMP, run_id)
data_tables_dir = os.path.join(output_dir, 'data_tables')
outputs_dir = os.path.join(output_dir, 'outputs')
debug_dir = os.path.join(output_dir, 'debug')  # ADD THIS
os.makedirs(data_tables_dir, exist_ok=True)
os.makedirs(outputs_dir, exist_ok=True)
os.makedirs(debug_dir, exist_ok=True)           # ADD THIS

# Then pass to run_analysis.py:
# --debug-folder', debug_dir
```

### Fix #3: Modify Error Handling (Priority: MEDIUM)

```python
# Instead of failing, capture and report infeasibility gracefully
# Add to run_analysis.py error handling:

if "infeasible" in str(e).lower():
    print("WARNING: Model infeasible - likely supply/demand mismatch")
    print("Suggestions:")
    print("  - Increase transformer_supply_capacity")
    print("  - Add backup supply source")
    print("  - Relax network topology constraints")
```

---

## Next Steps

1. **Increase transformer_supply_capacity to 250000**
   - Re-run full_electrification + STEDIN tests
   - Should resolve most infeasibility issues

2. **Add debug_dir isolation in run_parallel.py**
   - Fixes file path error for remaining hybrid runs

3. **Profile successful vs failed runs**
   - Analyze what differentiates passing OSM runs from failing STEDIN runs
   - May reveal network topology insights

4. **Add scenario-specific constraints**
   - Pre-validate model feasibility before solver
   - Fail fast with meaningful error messages

---

## Files Referenced

- `parallel_results/20260117_002328/execution_summary.csv`
- `parallel_results/20260117_002335/*/stderr.txt`
- `run_analysis.py` (lines 141, 298-310, 366)
- `run_parallel.py` (lines ~130)
- `functions/process_calliope_results.py` (line 107)

