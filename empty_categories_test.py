#!/usr/bin/env python3

import subprocess
import json
import yaml
import sys
import os

def test_empty_categories_scenario():
    """Test for the specific scenario that could lead to empty categories"""
    
    print("=== Testing Empty Categories Scenario ===")
    
    # Create environment with packages that might trigger the bug
    with open('env-empty-cat.yml', 'w') as f:
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
        "conda-lock", "-f", "env-empty-cat.yml", 
        "--lockfile", "empty-cat-lock.yml", "-p", "linux-64"
    ], capture_output=True, text=True)
    
    if result.returncode != 0:
        print(f"Error generating lockfile: {result.stderr}")
        return False
    
    print("✓ Lockfile generated")
    
    # Check if outputv2.json was generated
    if os.path.exists('outputv2.json'):
        print("✓ outputv2.json found - analyzing for empty categories...")
        
        with open('outputv2.json', 'r') as f:
            data = json.load(f)
        
        # Look for packages with empty categories
        empty_cat_packages = []
        for pkg in data.get('package', []):
            if pkg.get('categories') == []:
                empty_cat_packages.append({
                    'name': pkg['name'],
                    'manager': pkg.get('manager', 'unknown'),
                    'platform': pkg.get('platform', 'unknown'),
                    'dependencies': pkg.get('dependencies', [])
                })
        
        if empty_cat_packages:
            print(f"✗ BUG FOUND: Found {len(empty_cat_packages)} packages with empty categories:")
            for pkg in empty_cat_packages[:10]:  # Show first 10
                print(f"  - {pkg['name']} ({pkg['manager']}, {pkg['platform']})")
                if pkg['dependencies']:
                    print(f"    Dependencies: {pkg['dependencies']}")
            return True
        else:
            print("✓ No empty categories found in outputv2.json")
    else:
        print("✗ outputv2.json not found")
    
    return False

def test_update_scenario_with_complex_deps():
    """Test updating with complex dependencies that might trigger the bug"""
    
    print("\n=== Testing Update with Complex Dependencies ===")
    
    # Create initial environment
    with open('env-complex1.yml', 'w') as f:
        f.write("""name: test
channels:
  - conda-forge
dependencies:
  - python=3.9
  - numpy
  - scipy
  - scikit-learn
""")

    # Create updated environment with complex dependencies
    with open('env-complex2.yml', 'w') as f:
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
        "conda-lock", "-f", "env-complex1.yml", 
        "--lockfile", "complex-lock.yml", "-p", "linux-64"
    ], capture_output=True, text=True)
    
    if result.returncode != 0:
        print(f"Error creating lockfile: {result.stderr}")
        return False
    
    print("✓ Initial lockfile created")
    
    # Update lockfile
    print("Step 2: Updating lockfile...")
    result = subprocess.run([
        "conda-lock", "-f", "env-complex2.yml", 
        "--lockfile", "complex-lock.yml", "-p", "linux-64"
    ], capture_output=True, text=True)
    
    if result.returncode != 0:
        print(f"Error updating lockfile: {result.stderr}")
        return False
    
    print("✓ Lockfile updated")
    
    # Check if outputv2.json was generated during update
    if os.path.exists('outputv2.json'):
        print("✓ outputv2.json found - analyzing for empty categories...")
        
        with open('outputv2.json', 'r') as f:
            data = json.load(f)
        
        # Look for packages with empty categories
        empty_cat_packages = []
        for pkg in data.get('package', []):
            if pkg.get('categories') == []:
                empty_cat_packages.append({
                    'name': pkg['name'],
                    'manager': pkg.get('manager', 'unknown'),
                    'platform': pkg.get('platform', 'unknown'),
                    'dependencies': pkg.get('dependencies', [])
                })
        
        if empty_cat_packages:
            print(f"✗ BUG FOUND: Found {len(empty_cat_packages)} packages with empty categories:")
            for pkg in empty_cat_packages[:10]:  # Show first 10
                print(f"  - {pkg['name']} ({pkg['manager']}, {pkg['platform']})")
                if pkg['dependencies']:
                    print(f"    Dependencies: {pkg['dependencies']}")
            return True
        else:
            print("✓ No empty categories found in outputv2.json")
    else:
        print("✗ outputv2.json not found")
    
    return False

def test_validation_error_trigger():
    """Test for triggering the validation error"""
    
    print("\n=== Testing for Validation Error ===")
    
    # Try to install the complex lockfile and see if it fails
    if os.path.exists('complex-lock.yml'):
        print("Attempting installation to trigger validation error...")
        try:
            result = subprocess.run([
                "conda-lock", "install", "--name", "test-complex", "complex-lock.yml"
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
    print("Testing empty categories scenario...")
    bug_found = test_empty_categories_scenario()
    
    if not bug_found:
        print("\nTesting update with complex dependencies...")
        bug_found = test_update_scenario_with_complex_deps()
    
    if not bug_found:
        print("\nTesting for validation error...")
        bug_found = test_validation_error_trigger()
    
    if bug_found:
        print("\n🎉 POTENTIAL BUG FOUND!")
    else:
        print("\nNo obvious bug found in current tests")