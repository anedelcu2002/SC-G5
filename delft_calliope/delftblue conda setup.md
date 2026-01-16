# Setting Up Conda Environment on DelftBlue

This guide explains how to create a conda environment on DelftBlue that matches your local Calliope environment.

## Overview

You'll:
1. Export your local conda environment to a file
2. Transfer it to DelftBlue
3. Create the environment on DelftBlue
4. Update your SLURM script to use it

---

## Step 1: Export Your Local Environment

**On your Windows machine** (where you have Calliope installed):

```bash
cd ~/Documents/GitHub/SC-G5/delft_calliope

# Export your conda environment to a YAML file
conda env export > calliope_env.yml
```

This creates `calliope_env.yml` with all your packages and versions.

**Verify it was created:**
```bash
ls calliope_env.yml  # Should show the file
```

---

## Step 2: Transfer to DelftBlue

From your **Windows machine**, use PowerShell or Git Bash:

```bash
# Transfer the environment file to DelftBlue
scp calliope_env.yml <netid>@login.delftblue.tudelft.nl:/scratch/<netid>/

# Example:
# scp calliope_env.yml alexn@login.delftblue.tudelft.nl:/scratch/alexn/
```

---

## Step 3: Create Conda Environment on DelftBlue

Login to DelftBlue and set up your environment:

```bash
# Login to DelftBlue
ssh <netid>@login.delftblue.tudelft.nl

# Navigate to your scratch directory
cd /scratch/<netid>

# Load the miniconda module
module load miniconda3
module load openssh
module load git

# Important: Prevent conda from modifying your .bashrc
# This avoids conflicts between login node and compute nodes
unset CONDA_SHLVL
source "$(conda info --base)/etc/profile.d/conda.sh"

# Create the conda environment from your YAML file
conda env create -f calliope_env.yml

# This will take a few minutes - it downloads and installs all packages
```

**Verify the environment was created:**
```bash
conda env list

# You should see "calliope" in the list
```

---

## Step 4: Update SLURM Script to Use Conda

Edit [submit_parallel.sh](submit_parallel.sh) and replace the module loading section with:

```bash
# ============================================================================
# Load conda and activate environment
# ============================================================================

module load miniconda3
module load openssh
module load git

# Prevent conda from modifying .bashrc (important for compute nodes)
unset CONDA_SHLVL
source "$(conda info --base)/etc/profile.d/conda.sh"

# Activate your conda environment
conda activate calliope

# ============================================================================
# Load solver and other modules
# ============================================================================

module load gurobi/12.0.0
```

---

## Step 5: Test Locally (Optional)

Before submitting to DelftBlue, test that your conda environment works:

```bash
# On DelftBlue login node:
ssh <netid>@login.delftblue.tudelft.nl
cd /scratch/<netid>

module load miniconda3
module load openssh
module load git

unset CONDA_SHLVL
source "$(conda info --base)/etc/profile.d/conda.sh"

conda activate calliope

# Test imports
python -c "import calliope; import gurobi; print('Success!')"
```

---

## Important Notes

### Why `unset CONDA_SHLVL`?

DelftBlue documentation warns that `conda init` can cause problems on compute nodes because it modifies your `.bashrc` with paths that may not work across all nodes. The `unset CONDA_SHLVL` workaround allows conda to work on all nodes (login and compute) without this issue.

### Updating Your Environment

If you add new packages to your local Calliope environment, repeat the process:

```bash
# Local machine
conda env export > calliope_env.yml
scp calliope_env.yml <netid>@login.delftblue.tudelft.nl:/scratch/<netid>/

# DelftBlue
ssh <netid>@login.delftblue.tudelft.nl
cd /scratch/<netid>

module load miniconda3
module load openssh
module load git

unset CONDA_SHLVL
source "$(conda info --base)/etc/profile.d/conda.sh"

# Remove old environment and create new one
conda env remove -n calliope
conda env create -f calliope_env.yml
```

### Storage Location

Your conda environment is created in `/scratch/<netid>` which is:
- ✅ **Temporary** — Good for run-time data
- ✅ **Fast** — Local disk access
- ⚠️ **Periodically cleaned** — Keep a backup of `calliope_env.yml`

For permanent storage, you could use `/home/<netid>` but it has a 30GB limit.

---

## Troubleshooting

### "conda: command not found"
You forgot to load the module:
```bash
module load miniconda3
unset CONDA_SHLVL
source "$(conda info --base)/etc/profile.d/conda.sh"
```

### "miniconda3 conflicts with git"
DelftBlue's documentation warns about this. Always load the new modules:
```bash
module load miniconda3
module load openssh
module load git
```

### Environment creation is very slow
This is normal for large environments with many dependencies. Give it time.

### "ModuleNotFoundError: No module named 'calliope'"
Your conda environment isn't activated. Check:
```bash
conda activate calliope
python -c "import calliope; print(calliope.__version__)"
```

---

## Quick Reference

**Export environment (local machine):**
```bash
conda env export > calliope_env.yml
scp calliope_env.yml <netid>@login.delftblue.tudelft.nl:/scratch/<netid>/
```

**Create environment (DelftBlue):**
```bash
module load miniconda3 openssh git
unset CONDA_SHLVL
source "$(conda info --base)/etc/profile.d/conda.sh"
conda env create -f calliope_env.yml
```

**Use in SLURM script:**
```bash
module load miniconda3 openssh git
unset CONDA_SHLVL
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate calliope
module load gurobi/12.0.0
```

---

## Next Steps

1. ✅ Export your local Calliope environment: `conda env export > calliope_env.yml`
2. ✅ Transfer to DelftBlue: `scp calliope_env.yml <netid>@login.delftblue.tudelft.nl:/scratch/<netid>/`
3. ✅ Create environment on DelftBlue: `conda env create -f calliope_env.yml`
4. ✅ Update [submit_parallel.sh](submit_parallel.sh) with conda activation
5. ✅ Test: `python -c "import calliope; import gurobi; print('Success!')"`
6. ✅ Submit your first SLURM job: `bash manage_slurm.sh submit`
