#!/usr/bin/env python3

import subprocess
import json
import sys
import os

def run_conda_lock_with_debug():
    """Run conda-lock with debug output to see intermediate state"""
    
    print("=== Debugging conda-lock transitive dependency bug ===")
    
    # Step 1: Create initial lockfile
    print("Step 1: Creating initial lockfile...")
    result = subprocess.run([
        "conda-lock", "-f", "environment-v1.yml", 
        "--lockfile", "conda-lock.yml"
    ], capture_output=True, text=True)
    
    if result.returncode != 0:
        print(f"Error creating initial lockfile: {result.stderr}")
        return False
    
    print("✓ Initial lockfile created")
    
    # Step 2: Update with complex environment
    print("\nStep 2: Updating with complex environment...")
    result = subprocess.run([
        "conda-lock", "-f", "environment-v3.yml", 
        "--lockfile", "conda-lock.yml"
    ], capture_output=True, text=True)
    
    if result.returncode != 0:
        print(f"Error updating lockfile: {result.stderr}")
        return False
    
    print("✓ Lockfile updated")
    
    # Step 3: Check for output files
    print("\nStep 3: Checking for output files...")
    
    if os.path.exists("outputv2.json"):
        print("✓ outputv2.json found")
        with open("outputv2.json", "r") as f:
            data = json.load(f)
        
        # Look for packages with empty categories
        empty_categories = []
        for pkg in data.get("package", []):
            if pkg.get("categories") == []:
                empty_categories.append(pkg["name"])
        
        if empty_categories:
            print(f"✗ BUG FOUND: {len(empty_categories)} packages with empty categories:")
            for pkg in empty_categories:
                print(f"  - {pkg}")
            return True
        else:
            print("✓ No packages with empty categories found")
    else:
        print("✗ outputv2.json not found")
    
    if os.path.exists("outputv1.json"):
        print("✓ outputv1.json found")
    else:
        print("✗ outputv1.json not found")
    
    return False

if __name__ == "__main__":
    bug_found = run_conda_lock_with_debug()
    if bug_found:
        print("\n🎯 BUG SUCCESSFULLY REPRODUCED!")
        sys.exit(1)
    else:
        print("\n❌ Bug not reproduced in this scenario")
        sys.exit(0)