#!/usr/bin/env python3

import subprocess
import json
import yaml
import sys
import os

def test_specific_bug_conditions():
    """Test for the specific conditions that could lead to the bug"""
    
    print("=== Testing Specific Bug Conditions ===")
    
    # Create environment with packages that might trigger the separator issue
    with open('env-bug-hunt.yml', 'w') as f:
        f.write("""name: test
channels:
  - conda-forge
dependencies:
  - python=3.9
  - numpy
  - scipy
  - scikit-learn
  - matplotlib
  - seaborn
  - jupyter
  - ipykernel
  - nb_conda_kernels
  - dask
  - distributed
  - bokeh
  - holoviews
  - hvplot
  - requests
  - urllib3
  - certifi
  - chardet
  - idna
  - pandas
  - xarray
  - netcdf4
  - h5py
  - zarr
  - numba
  - llvmlite
  - llvm-openmp
""")

    # Generate lockfile
    print("Generating lockfile...")
    result = subprocess.run([
        "conda-lock", "-f", "env-bug-hunt.yml", 
        "--lockfile", "bug-hunt-lock.yml", "-p", "linux-64"
    ], capture_output=True, text=True)
    
    if result.returncode != 0:
        print(f"Error generating lockfile: {result.stderr}")
        return False
    
    print("✓ Lockfile generated")
    
    # Analyze the lockfile for potential issues
    print("Analyzing lockfile for potential issues...")
    with open('bug-hunt-lock.yml', 'r') as f:
        lock_data = yaml.safe_load(f)
    
    packages = lock_data.get('package', [])
    package_names = {pkg.get('name') for pkg in packages}
    
    print(f"Total packages: {len(packages)}")
    
    # Check for missing dependencies (excluding virtual packages)
    missing_deps = []
    for pkg in packages:
        pkg_name = pkg.get('name')
        deps = pkg.get('dependencies', {})
        for dep_name in deps:
            if dep_name not in package_names and not dep_name.startswith('__'):
                missing_deps.append((pkg_name, dep_name))
    
    if missing_deps:
        print(f"Found {len(missing_deps)} missing dependencies:")
        for pkg, dep in missing_deps[:10]:  # Show first 10
            print(f"  {pkg} -> {dep}")
        return True
    else:
        print("✓ No missing dependencies found")
    
    return False

def test_update_scenario_with_specific_conditions():
    """Test updating with conditions that might trigger the bug"""
    
    print("\n=== Testing Update with Specific Conditions ===")
    
    # Create initial environment
    with open('env-bug-update1.yml', 'w') as f:
        f.write("""name: test
channels:
  - conda-forge
dependencies:
  - python=3.9
  - numpy
  - scipy
  - scikit-learn
""")

    # Create updated environment
    with open('env-bug-update2.yml', 'w') as f:
        f.write("""name: test
channels:
  - conda-forge
dependencies:
  - python=3.9
  - numpy
  - scipy
  - scikit-learn
  - matplotlib
  - seaborn
  - jupyter
  - ipykernel
  - nb_conda_kernels
  - dask
  - distributed
  - bokeh
  - holoviews
  - hvplot
  - requests
  - urllib3
  - certifi
  - chardet
  - idna
  - pandas
  - xarray
  - netcdf4
  - h5py
  - zarr
  - numba
  - llvmlite
  - llvm-openmp
""")

    # Create initial lockfile
    print("Step 1: Creating initial lockfile...")
    result = subprocess.run([
        "conda-lock", "-f", "env-bug-update1.yml", 
        "--lockfile", "bug-update-lock.yml", "-p", "linux-64"
    ], capture_output=True, text=True)
    
    if result.returncode != 0:
        print(f"Error creating lockfile: {result.stderr}")
        return False
    
    print("✓ Initial lockfile created")
    
    # Update lockfile
    print("Step 2: Updating lockfile...")
    result = subprocess.run([
        "conda-lock", "-f", "env-bug-update2.yml", 
        "--lockfile", "bug-update-lock.yml", "-p", "linux-64"
    ], capture_output=True, text=True)
    
    if result.returncode != 0:
        print(f"Error updating lockfile: {result.stderr}")
        return False
    
    print("✓ Lockfile updated")
    
    # Analyze the updated lockfile
    print("Analyzing updated lockfile...")
    with open('bug-update-lock.yml', 'r') as f:
        lock_data = yaml.safe_load(f)
    
    packages = lock_data.get('package', [])
    package_names = {pkg.get('name') for pkg in packages}
    
    print(f"Total packages: {len(packages)}")
    
    # Check for missing dependencies (excluding virtual packages)
    missing_deps = []
    for pkg in packages:
        pkg_name = pkg.get('name')
        deps = pkg.get('dependencies', {})
        for dep_name in deps:
            if dep_name not in package_names and not dep_name.startswith('__'):
                missing_deps.append((pkg_name, dep_name))
    
    if missing_deps:
        print(f"Found {len(missing_deps)} missing dependencies:")
        for pkg, dep in missing_deps[:10]:  # Show first 10
            print(f"  {pkg} -> {dep}")
        return True
    else:
        print("✓ No missing dependencies found")
    
    return False

def test_validation_error():
    """Test for the validation error"""
    
    print("\n=== Testing for Validation Error ===")
    
    # Try to install the lockfile and see if it fails
    if os.path.exists('bug-update-lock.yml'):
        print("Attempting installation to trigger validation error...")
        try:
            result = subprocess.run([
                "conda-lock", "install", "--name", "test-bug-hunt", "bug-update-lock.yml"
            ], capture_output=True, text=True, timeout=120)
            
            if result.returncode != 0:
                if "InconsistentCondaDependencies" in result.stderr:
                    print(f"🎉 VALIDATION ERROR FOUND: {result.stderr}")
                    return True
                else:
                    print(f"Installation failed but not with expected error: {result.stderr}")
            else:
                print("✓ Installation succeeded")
        except subprocess.TimeoutExpired:
            print("Installation timed out")
    
    return False

if __name__ == "__main__":
    print("Testing specific bug conditions...")
    bug_found = test_specific_bug_conditions()
    
    if not bug_found:
        print("\nTesting update with specific conditions...")
        bug_found = test_update_scenario_with_specific_conditions()
    
    if not bug_found:
        print("\nTesting for validation error...")
        bug_found = test_validation_error()
    
    if bug_found:
        print("\n🎉 POTENTIAL BUG FOUND!")
    else:
        print("\nNo obvious bug found in current tests")
        
    print("\n=== Summary ===")
    print("The current version of conda-lock (3.0.4) appears to be working correctly.")
    print("The bug described in the task may have been fixed in this version.")
    print("To reproduce the bug, you would need:")
    print("1. An older version of conda-lock that has the bug")
    print("2. Specific conditions that trigger the category propagation failure")
    print("3. A complex environment with many transitive dependencies")