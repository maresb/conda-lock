#!/bin/bash

set -e

echo "=== Testing complex conda-lock transitive dependency bug reproducer ==="

# Step 1: Create initial lockfile with minimal dependencies
echo "Step 1: Creating initial lockfile with minimal dependencies"
conda-lock -f environment-v1.yml --lockfile conda-lock.yml

echo "Initial lockfile created."

# Step 2: Try updating with a complex environment
echo ""
echo "Step 2: Updating with complex environment (environment-v3.yml)"
conda-lock -f environment-v3.yml --lockfile conda-lock.yml

echo "Complex update completed."

# Step 3: Try updating specific packages
echo ""
echo "Step 3: Trying to update specific packages"
conda-lock -f environment-v3.yml --lockfile conda-lock.yml --update numpy

echo "Package update completed."

# Step 4: Check for output files and analyze
echo ""
echo "Step 4: Checking for output files and analyzing..."

if [ -f outputv2.json ]; then
    echo "✓ outputv2.json found - analyzing for empty categories..."
    
    # Look for packages with empty categories
    if grep -q '"categories": \[\]' outputv2.json; then
        echo "✗ BUG FOUND: Found packages with empty categories in outputv2.json"
        echo "Packages with empty categories:"
        grep -B 2 -A 2 '"categories": \[\]' outputv2.json
    else
        echo "✓ No empty categories found in outputv2.json"
    fi
    
    # Look for packages that might be missing
    echo "Analyzing package dependencies..."
    python3 -c "
import json
with open('outputv2.json', 'r') as f:
    data = json.load(f)

# Find packages with dependencies
packages_with_deps = []
for pkg in data['package']:
    if pkg.get('dependencies'):
        packages_with_deps.append({
            'name': pkg['name'],
            'dependencies': pkg['dependencies'],
            'categories': pkg.get('categories', [])
        })

print(f'Found {len(packages_with_deps)} packages with dependencies')
for pkg in packages_with_deps[:5]:  # Show first 5
    print(f'  {pkg[\"name\"]}: deps={len(pkg[\"dependencies\"])}, cats={pkg[\"categories\"]}')
"
else
    echo "✗ outputv2.json not found"
fi

if [ -f outputv1.json ]; then
    echo "✓ outputv1.json found"
else
    echo "✗ outputv1.json not found"
fi

echo ""
echo "=== Complex reproducer test completed ==="