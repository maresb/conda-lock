#!/usr/bin/env python3

import subprocess
import json
import yaml
import sys
import os

def test_separator_issue():
    """Test for the separator issue that could lead to empty categories"""
    
    print("=== Testing Separator Issue for Empty Categories ===")
    
    # Create environment with packages that might have separator issues
    with open('env-separator-bug.yml', 'w') as f:
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
  - ld_impl_linux-64
""")

    # Generate lockfile
    print("Generating lockfile with potential separator issues...")
    result = subprocess.run([
        "conda-lock", "-f", "env-separator-bug.yml", 
        "--lockfile", "separator-bug-lock.yml", "-p", "linux-64"
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
    
    # Try to install and see if it fails
    print("Attempting installation to trigger validation...")
    try:
        result = subprocess.run([
            "conda-lock", "install", "--name", "test-separator-bug", "separator-bug-lock.yml"
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

def test_update_with_separator_issue():
    """Test updating a lockfile with potential separator issues"""
    
    print("\n=== Testing Update with Separator Issue ===")
    
    # Create initial environment
    with open('env-separator-update1.yml', 'w') as f:
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
    with open('env-separator-update2.yml', 'w') as f:
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
  - ld_impl_linux-64
""")

    # Create initial lockfile
    print("Step 1: Creating initial lockfile...")
    result = subprocess.run([
        "conda-lock", "-f", "env-separator-update1.yml", 
        "--lockfile", "separator-update-lock.yml", "-p", "linux-64"
    ], capture_output=True, text=True)
    
    if result.returncode != 0:
        print(f"Error creating lockfile: {result.stderr}")
        return False
    
    print("✓ Initial lockfile created")
    
    # Update lockfile
    print("Step 2: Updating lockfile...")
    result = subprocess.run([
        "conda-lock", "-f", "env-separator-update2.yml", 
        "--lockfile", "separator-update-lock.yml", "-p", "linux-64"
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

if __name__ == "__main__":
    print("Testing separator issue...")
    bug_found = test_separator_issue()
    
    if not bug_found:
        print("\nTesting update with separator issue...")
        bug_found = test_update_with_separator_issue()
    
    if bug_found:
        print("\n🎉 POTENTIAL BUG FOUND!")
    else:
        print("\nNo obvious bug found in current tests")