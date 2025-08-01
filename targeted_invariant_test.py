#!/usr/bin/env python3

import subprocess
import json
import yaml
import sys
import os

def test_category_propagation_bug():
    """Test for the specific category propagation bug"""
    
    print("=== Testing Category Propagation Bug ===")
    
    # Step 1: Create environment with packages that have complex transitive dependencies
    with open('env-category1.yml', 'w') as f:
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

    # Step 2: Create a modified environment that removes some packages but keeps others
    with open('env-category2.yml', 'w') as f:
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
""")

    # Step 3: Create initial lockfile
    print("Step 1: Creating initial lockfile...")
    result = subprocess.run([
        "conda-lock", "-f", "env-category1.yml", 
        "--lockfile", "category-lock.yml", "-p", "linux-64"
    ], capture_output=True, text=True)
    
    if result.returncode != 0:
        print(f"Error creating lockfile: {result.stderr}")
        return False
    
    print("✓ Initial lockfile created")
    
    # Step 4: Update with modified environment
    print("Step 2: Updating with modified environment...")
    result = subprocess.run([
        "conda-lock", "-f", "env-category2.yml", 
        "--lockfile", "category-lock.yml", "-p", "linux-64"
    ], capture_output=True, text=True)
    
    if result.returncode != 0:
        print(f"Error updating lockfile: {result.stderr}")
        return False
    
    print("✓ Lockfile updated")
    
    # Step 5: Try to install and see if it fails
    print("Step 3: Attempting installation to trigger validation...")
    try:
        result = subprocess.run([
            "conda-lock", "install", "--name", "test-category", "category-lock.yml"
        ], capture_output=True, text=True, timeout=120)
        
        if result.returncode != 0:
            print(f"Installation failed (potential bug found!): {result.stderr}")
            return True
        else:
            print("✓ Installation succeeded")
    except subprocess.TimeoutExpired:
        print("Installation timed out")
    
    # Step 6: Examine the lockfile for potential issues
    print("Step 4: Examining lockfile for potential issues...")
    with open('category-lock.yml', 'r') as f:
        lock_data = yaml.safe_load(f)
    
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

def test_separator_issues():
    """Test for separator-related issues that could lead to empty categories"""
    
    print("\n=== Testing Separator Issues ===")
    
    # Create environment with packages that might have separator issues
    with open('env-separator.yml', 'w') as f:
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
        "conda-lock", "-f", "env-separator.yml", 
        "--lockfile", "separator-lock.yml", "-p", "linux-64"
    ], capture_output=True, text=True)
    
    if result.returncode != 0:
        print(f"Error generating lockfile: {result.stderr}")
        return False
    
    print("✓ Lockfile generated")
    
    # Try to install and see if it fails
    print("Attempting installation to trigger validation...")
    try:
        result = subprocess.run([
            "conda-lock", "install", "--name", "test-separator", "separator-lock.yml"
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
    print("Testing category propagation bug...")
    bug_found = test_category_propagation_bug()
    
    if not bug_found:
        print("\nTesting separator issues...")
        bug_found = test_separator_issues()
    
    if bug_found:
        print("\n🎉 POTENTIAL BUG FOUND!")
    else:
        print("\nNo obvious bug found in current tests")