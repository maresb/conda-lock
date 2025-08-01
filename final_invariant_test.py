#!/usr/bin/env python3

import subprocess
import json
import yaml
import sys
import os

def test_update_scenario():
    """Test the specific update scenario that could lead to empty categories"""
    
    print("=== Testing Update Scenario for Empty Categories ===")
    
    # Step 1: Create initial environment with packages that have complex transitive dependencies
    with open('env-update1.yml', 'w') as f:
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

    # Step 2: Create initial lockfile
    print("Step 1: Creating initial lockfile...")
    result = subprocess.run([
        "conda-lock", "-f", "env-update1.yml", 
        "--lockfile", "update-lock.yml", "-p", "linux-64"
    ], capture_output=True, text=True)
    
    if result.returncode != 0:
        print(f"Error creating lockfile: {result.stderr}")
        return False
    
    print("✓ Initial lockfile created")
    
    # Step 3: Update with specific packages that might cause issues
    print("Step 2: Updating with specific packages...")
    result = subprocess.run([
        "conda-lock", "-f", "env-update1.yml", 
        "--lockfile", "update-lock.yml", "-p", "linux-64", "--update", "numpy"
    ], capture_output=True, text=True)
    
    if result.returncode != 0:
        print(f"Error updating lockfile: {result.stderr}")
        return False
    
    print("✓ Lockfile updated")
    
    # Step 4: Try to install and see if it fails
    print("Step 3: Attempting installation to trigger validation...")
    try:
        result = subprocess.run([
            "conda-lock", "install", "--name", "test-update", "update-lock.yml"
        ], capture_output=True, text=True, timeout=120)
        
        if result.returncode != 0:
            print(f"Installation failed (potential bug found!): {result.stderr}")
            return True
        else:
            print("✓ Installation succeeded")
    except subprocess.TimeoutExpired:
        print("Installation timed out")
    
    # Step 5: Examine the lockfile for potential issues
    print("Step 4: Examining lockfile for potential issues...")
    with open('update-lock.yml', 'r') as f:
        lock_data = yaml.safe_load(f)
    
    packages = lock_data.get('package', [])  # Fixed: use 'package' not 'packages'
    dependencies = lock_data.get('dependencies', {})
    
    print(f"Total packages: {len(packages)}")
    print(f"Total dependencies: {len(dependencies)}")
    
    # Check for packages that might have empty categories
    potential_issues = []
    for pkg_data in packages:  # Fixed: iterate over list, not dict
        pkg_name = pkg_data.get('name', 'unknown')
        if 'category' not in pkg_data:
            potential_issues.append(f"Package {pkg_name} missing category")
        elif pkg_data['category'] == []:
            potential_issues.append(f"Package {pkg_name} has empty category")
    
    # Check for dependencies that reference non-existent packages
    package_names = {pkg.get('name') for pkg in packages}
    for pkg_data in packages:
        pkg_name = pkg_data.get('name', 'unknown')
        deps = pkg_data.get('dependencies', {})
        for dep_name in deps:
            if dep_name not in package_names:
                potential_issues.append(f"Package {pkg_name} references non-existent dependency {dep_name}")
    
    if potential_issues:
        print("Potential issues found:")
        for issue in potential_issues[:10]:  # Show first 10
            print(f"  - {issue}")
        return True
    else:
        print("No obvious issues found in lockfile")
    
    return False

def test_merge_scenario():
    """Test the merge scenario that could lead to empty categories"""
    
    print("\n=== Testing Merge Scenario for Empty Categories ===")
    
    # Create environment with packages that have complex transitive dependencies
    with open('env-merge.yml', 'w') as f:
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
    print("Generating lockfile with complex dependencies...")
    result = subprocess.run([
        "conda-lock", "-f", "env-merge.yml", 
        "--lockfile", "merge-lock.yml", "-p", "linux-64"
    ], capture_output=True, text=True)
    
    if result.returncode != 0:
        print(f"Error generating lockfile: {result.stderr}")
        return False
    
    print("✓ Lockfile generated")
    
    # Try to install and see if it fails
    print("Attempting installation to trigger validation...")
    try:
        result = subprocess.run([
            "conda-lock", "install", "--name", "test-merge", "merge-lock.yml"
        ], capture_output=True, text=True, timeout=120)
        
        if result.returncode != 0:
            print(f"Installation failed (potential bug found!): {result.stderr}")
            return True
        else:
            print("✓ Installation succeeded")
    except subprocess.TimeoutExpired:
        print("Installation timed out")
    
    return False

def test_validation_error():
    """Test for the specific validation error that indicates the bug"""
    
    print("\n=== Testing for Validation Error ===")
    
    # Create a minimal environment that might trigger the bug
    with open('env-validate.yml', 'w') as f:
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
        "conda-lock", "-f", "env-validate.yml", 
        "--lockfile", "validate-lock.yml", "-p", "linux-64"
    ], capture_output=True, text=True)
    
    if result.returncode != 0:
        print(f"Error generating lockfile: {result.stderr}")
        return False
    
    print("✓ Lockfile generated")
    
    # Try to install and see if it fails with validation error
    print("Attempting installation to trigger validation error...")
    try:
        result = subprocess.run([
            "conda-lock", "install", "--name", "test-validate", "validate-lock.yml"
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
    print("Testing update scenario...")
    bug_found = test_update_scenario()
    
    if not bug_found:
        print("\nTesting merge scenario...")
        bug_found = test_merge_scenario()
    
    if not bug_found:
        print("\nTesting for validation error...")
        bug_found = test_validation_error()
    
    if bug_found:
        print("\n🎉 POTENTIAL BUG FOUND!")
    else:
        print("\nNo obvious bug found in current tests")