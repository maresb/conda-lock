#!/usr/bin/env python3

import subprocess
import json
import yaml
import sys
import os

def create_environment_files():
    """Create environment files that target specific precursors"""
    
    # Precursor 1: Orphaned packages from lockfile updates
    with open('env-orphaned.yml', 'w') as f:
        f.write("""name: test
channels:
  - conda-forge
dependencies:
  - python=3.9
  - requests  # depends on urllib3, certifi, chardet, idna
""")

    with open('env-orphaned-update.yml', 'w') as f:
        f.write("""name: test
channels:
  - conda-forge
dependencies:
  - python=3.9
  - urllib3  # was transitive dep of requests, now direct
  - certifi  # was transitive dep of requests, now direct
  # Note: chardet and idna are no longer needed but might remain in lockfile
""")

    # Precursor 2: Separator issues (if any packages have inconsistent naming)
    with open('env-separator.yml', 'w') as f:
        f.write("""name: test
channels:
  - conda-forge
dependencies:
  - python=3.9
  - scikit-learn  # might have packages with separator issues
  - matplotlib
""")

def analyze_lockfile_for_precursors(lockfile_path):
    """Analyze lockfile for signs of the precursors"""
    
    with open(lockfile_path, 'r') as f:
        data = yaml.safe_load(f)
    
    packages = data.get('package', [])
    print(f"Analyzing {len(packages)} packages for precursors...")
    
    # Check for Precursor 1: Orphaned packages
    orphaned_candidates = []
    for pkg in packages:
        name = pkg.get('name', '')
        category = pkg.get('category', '')
        deps = pkg.get('dependencies', {})
        
        # Look for packages that might be orphaned
        if name in ['chardet', 'idna'] and category == 'main':
            # These were originally transitive deps of requests
            orphaned_candidates.append({
                'name': name,
                'category': category,
                'dependencies': deps
            })
    
    if orphaned_candidates:
        print(f"Found {len(orphaned_candidates)} potentially orphaned packages:")
        for pkg in orphaned_candidates:
            print(f"  - {pkg['name']} (category: {pkg['category']})")
    else:
        print("No obvious orphaned packages found")
    
    # Check for Precursor 2: Separator issues
    separator_issues = []
    for pkg in packages:
        name = pkg.get('name', '')
        if '-' in name and '_' in name:
            separator_issues.append(name)
    
    if separator_issues:
        print(f"Found {len(separator_issues)} packages with potential separator issues:")
        for name in separator_issues:
            print(f"  - {name}")
    else:
        print("No obvious separator issues found")
    
    # Check for Precursor 3: Empty categories (if output files exist)
    if os.path.exists('outputv2.json'):
        with open('outputv2.json', 'r') as f:
            output_data = json.load(f)
        
        empty_cat_packages = []
        for pkg in output_data.get('package', []):
            if pkg.get('categories') == []:
                empty_cat_packages.append(pkg['name'])
        
        if empty_cat_packages:
            print(f"Found {len(empty_cat_packages)} packages with empty categories:")
            for name in empty_cat_packages:
                print(f"  - {name}")
        else:
            print("No packages with empty categories found")

def test_precursor_1():
    """Test Precursor 1: Orphaned packages from lockfile updates"""
    print("\n=== Testing Precursor 1: Orphaned packages ===")
    
    # Step 1: Create lockfile with requests
    subprocess.run([
        "conda-lock", "-f", "env-orphaned.yml", 
        "--lockfile", "precursor1-lock.yml", "-p", "linux-64"
    ], check=True)
    
    # Step 2: Update to environment without requests
    subprocess.run([
        "conda-lock", "-f", "env-orphaned-update.yml", 
        "--lockfile", "precursor1-lock.yml", "-p", "linux-64"
    ], check=True)
    
    # Step 3: Analyze for orphaned packages
    analyze_lockfile_for_precursors("precursor1-lock.yml")

def test_precursor_2():
    """Test Precursor 2: Separator issues"""
    print("\n=== Testing Precursor 2: Separator issues ===")
    
    # Create lockfile with packages that might have separator issues
    subprocess.run([
        "conda-lock", "-f", "env-separator.yml", 
        "--lockfile", "precursor2-lock.yml", "-p", "linux-64"
    ], check=True)
    
    # Analyze for separator issues
    analyze_lockfile_for_precursors("precursor2-lock.yml")

def main():
    print("=== Invariant-based conda-lock empty categories reproducer ===")
    
    # Create environment files
    create_environment_files()
    
    # Test each precursor
    test_precursor_1()
    test_precursor_2()
    
    print("\n=== Invariant reproducer completed ===")

if __name__ == "__main__":
    main()