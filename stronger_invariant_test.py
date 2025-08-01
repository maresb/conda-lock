#!/usr/bin/env python3

import subprocess
import json
import yaml
import sys
import os
import tempfile

def test_stronger_invariants():
    """Test stronger invariants that should prevent empty categories"""
    
    print("=== Testing Stronger Invariants for Empty Categories ===")
    
    # Create environment that should trigger the bug
    with open('env-strong.yml', 'w') as f:
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
""")

    # Step 1: Create initial lockfile
    print("Step 1: Creating initial lockfile...")
    result = subprocess.run([
        "conda-lock", "-f", "env-strong.yml", 
        "--lockfile", "strong-lock.yml", "-p", "linux-64"
    ], capture_output=True, text=True)
    
    if result.returncode != 0:
        print(f"Error creating lockfile: {result.stderr}")
        return False
    
    print("✓ Initial lockfile created")
    
    # Step 2: Try to force the bug by updating with a modified environment
    with open('env-strong-update.yml', 'w') as f:
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
  - dask-array
""")

    print("Step 2: Updating with additional packages...")
    result = subprocess.run([
        "conda-lock", "-f", "env-strong-update.yml", 
        "--lockfile", "strong-lock.yml", "-p", "linux-64"
    ], capture_output=True, text=True)
    
    if result.returncode != 0:
        print(f"Error updating lockfile: {result.stderr}")
        return False
    
    print("✓ Lockfile updated")
    
    # Step 3: Try to trigger validation error by installing
    print("Step 3: Attempting to install to trigger validation...")
    try:
        result = subprocess.run([
            "conda-lock", "install", "--name", "test-strong", "strong-lock.yml"
        ], capture_output=True, text=True, timeout=60)
        
        if result.returncode != 0:
            print(f"Installation failed (this might be the bug!): {result.stderr}")
            return True  # This might be the bug!
        else:
            print("✓ Installation succeeded")
    except subprocess.TimeoutExpired:
        print("Installation timed out")
    
    # Step 4: Examine the lockfile for potential issues
    print("Step 4: Examining lockfile for potential issues...")
    with open('strong-lock.yml', 'r') as f:
        lock_data = yaml.safe_load(f)
    
    # Check for packages with empty categories or missing dependencies
    packages = lock_data.get('packages', {})
    dependencies = lock_data.get('dependencies', {})
    
    print(f"Total packages: {len(packages)}")
    print(f"Total dependencies: {len(dependencies)}")
    
    # Check for packages that might have empty categories
    potential_issues = []
    for pkg_name, pkg_data in packages.items():
        if 'category' not in pkg_data:
            potential_issues.append(f"Package {pkg_name} missing category")
        elif pkg_data['category'] == []:
            potential_issues.append(f"Package {pkg_name} has empty category")
    
    # Check for dependencies that reference non-existent packages
    for dep_name, dep_data in dependencies.items():
        for dep_pkg in dep_data:
            if dep_pkg not in packages:
                potential_issues.append(f"Dependency {dep_name} references non-existent package {dep_pkg}")
    
    if potential_issues:
        print("Potential issues found:")
        for issue in potential_issues[:10]:  # Show first 10
            print(f"  - {issue}")
        return True
    else:
        print("No obvious issues found in lockfile")
    
    return False

def test_v2_model_generation():
    """Test the v2 model generation process directly"""
    
    print("\n=== Testing V2 Model Generation ===")
    
    # Create a minimal environment that might trigger the bug
    with open('env-v2-test.yml', 'w') as f:
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
  - dask-array
  - numba
  - llvmlite
  - llvm-openmp
  - libgomp
  - libgcc-ng
  - libstdcxx-ng
  - libffi
  - libuuid
  - libnsl
  - readline
  - tzdata
  - ca-certificates
  - openssl
  - xz
  - zlib
  - bzip2
  - lz4
  - zstd
  - libblas
  - libcblas
  - liblapack
  - libopenblas
  - libgfortran
  - libgfortran5
  - libquadmath
  - libgcc-ng
  - libstdcxx-ng
  - libgomp
  - libffi
  - libuuid
  - libnsl
  - readline
  - tzdata
  - ca-certificates
  - openssl
  - xz
  - zlib
  - bzip2
  - lz4
  - zstd
  - libblas
  - libcblas
  - liblapack
  - libopenblas
  - libgfortran
  - libgfortran5
  - libquadmath
""")

    # Try to generate lockfile and examine intermediate state
    print("Generating lockfile with extensive dependencies...")
    result = subprocess.run([
        "conda-lock", "-f", "env-v2-test.yml", 
        "--lockfile", "v2-test-lock.yml", "-p", "linux-64"
    ], capture_output=True, text=True)
    
    if result.returncode != 0:
        print(f"Error generating lockfile: {result.stderr}")
        return False
    
    print("✓ Lockfile generated")
    
    # Try to install and see if it fails
    print("Attempting installation to trigger validation...")
    try:
        result = subprocess.run([
            "conda-lock", "install", "--name", "test-v2", "v2-test-lock.yml"
        ], capture_output=True, text=True, timeout=120)
        
        if result.returncode != 0:
            print(f"Installation failed (potential bug found!): {result.stderr}")
            return True
        else:
            print("✓ Installation succeeded")
    except subprocess.TimeoutExpired:
        print("Installation timed out")
    
    return False

if __name__ == "__main__":
    print("Testing stronger invariants...")
    bug_found = test_stronger_invariants()
    
    if not bug_found:
        print("\nTesting v2 model generation...")
        bug_found = test_v2_model_generation()
    
    if bug_found:
        print("\n🎉 POTENTIAL BUG FOUND!")
    else:
        print("\nNo obvious bug found in current tests")