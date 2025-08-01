#!/usr/bin/env python3

import subprocess
import json
import yaml
import sys
import os

def test_invariant_violations():
    """Test specific invariant violations that could lead to empty categories"""
    
    print("=== Testing Invariant Violations for Empty Categories ===")
    
    # Create environment files that target specific invariant violations
    with open('env-invariant1.yml', 'w') as f:
        f.write("""name: test
channels:
  - conda-forge
dependencies:
  - python=3.9
  - numpy
  - scipy  # depends on numpy, but might have version conflicts
""")

    with open('env-invariant2.yml', 'w') as f:
        f.write("""name: test
channels:
  - conda-forge
dependencies:
  - python=3.9
  - numpy
  - scikit-learn  # depends on numpy, scipy, joblib
  - matplotlib  # depends on numpy
""")

    with open('env-invariant3.yml', 'w') as f:
        f.write("""name: test
channels:
  - conda-forge
dependencies:
  - python=3.9
  - numpy
  - scikit-learn
  - matplotlib
  - seaborn  # depends on numpy, pandas, matplotlib
  - pandas  # depends on numpy
""")

    # Test 1: Version conflicts that might cause orphaned packages
    print("\n--- Test 1: Version conflicts ---")
    subprocess.run([
        "conda-lock", "-f", "env-invariant1.yml", 
        "--lockfile", "invariant1-lock.yml", "-p", "linux-64"
    ], check=True)
    
    subprocess.run([
        "conda-lock", "-f", "env-invariant2.yml", 
        "--lockfile", "invariant1-lock.yml", "-p", "linux-64"
    ], check=True)
    
    # Test 2: Complex dependency chains
    print("\n--- Test 2: Complex dependency chains ---")
    subprocess.run([
        "conda-lock", "-f", "env-invariant3.yml", 
        "--lockfile", "invariant2-lock.yml", "-p", "linux-64"
    ], check=True)
    
    # Test 3: Update specific packages to trigger potential issues
    print("\n--- Test 3: Package updates ---")
    subprocess.run([
        "conda-lock", "-f", "env-invariant3.yml", 
        "--lockfile", "invariant2-lock.yml", "-p", "linux-64", "--update", "numpy"
    ], check=True)
    
    # Analyze results
    analyze_invariant_violations()

def analyze_invariant_violations():
    """Analyze lockfiles for invariant violations"""
    
    print("\n--- Analyzing for Invariant Violations ---")
    
    # Check for output files that would indicate the bug
    if os.path.exists('outputv2.json'):
        print("✓ outputv2.json found - analyzing for empty categories...")
        with open('outputv2.json', 'r') as f:
            data = json.load(f)
        
        empty_cat_packages = []
        for pkg in data.get('package', []):
            if pkg.get('categories') == []:
                empty_cat_packages.append({
                    'name': pkg['name'],
                    'version': pkg.get('version', 'unknown'),
                    'manager': pkg.get('manager', 'unknown'),
                    'platform': pkg.get('platform', 'unknown'),
                    'dependencies': pkg.get('dependencies', [])
                })
        
        if empty_cat_packages:
            print(f"✗ INVARIANT VIOLATION: Found {len(empty_cat_packages)} packages with empty categories:")
            for pkg in empty_cat_packages:
                print(f"  - {pkg['name']} {pkg['version']} ({pkg['manager']}, {pkg['platform']})")
                if pkg['dependencies']:
                    print(f"    Dependencies: {pkg['dependencies']}")
            return True
        else:
            print("✓ No invariant violations found")
    else:
        print("✗ outputv2.json not found")
    
    # Check for potential orphaned packages in lockfiles
    for lockfile in ['invariant1-lock.yml', 'invariant2-lock.yml']:
        if os.path.exists(lockfile):
            print(f"\n--- Analyzing {lockfile} ---")
            analyze_lockfile_for_orphans(lockfile)
    
    return False

def analyze_lockfile_for_orphans(lockfile_path):
    """Analyze lockfile for orphaned packages"""
    
    with open(lockfile_path, 'r') as f:
        data = yaml.safe_load(f)
    
    packages = data.get('package', [])
    
    # Build dependency graph
    deps_graph = {}
    reverse_deps = {}
    
    for pkg in packages:
        name = pkg.get('name', '')
        deps = pkg.get('dependencies', {})
        deps_graph[name] = list(deps.keys())
        
        for dep in deps.keys():
            if dep not in reverse_deps:
                reverse_deps[dep] = []
            reverse_deps[dep].append(name)
    
    # Find potentially orphaned packages
    orphaned_candidates = []
    for pkg in packages:
        name = pkg.get('name', '')
        category = pkg.get('category', '')
        
        # Check if package has no dependents (except itself)
        dependents = reverse_deps.get(name, [])
        if len(dependents) <= 1 and category == 'main':
            # This might be an orphaned package
            orphaned_candidates.append({
                'name': name,
                'category': category,
                'dependents': dependents
            })
    
    if orphaned_candidates:
        print(f"Found {len(orphaned_candidates)} potentially orphaned packages:")
        for pkg in orphaned_candidates:
            print(f"  - {pkg['name']} (category: {pkg['category']}, dependents: {pkg['dependents']})")
    else:
        print("No obvious orphaned packages found")

def main():
    print("=== Invariant Violation Test for Empty Categories ===")
    
    try:
        bug_found = test_invariant_violations()
        if bug_found:
            print("\n🎯 INVARIANT VIOLATION DETECTED - BUG REPRODUCED!")
            sys.exit(1)
        else:
            print("\n❌ No invariant violations detected")
            sys.exit(0)
    except Exception as e:
        print(f"Error during testing: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()