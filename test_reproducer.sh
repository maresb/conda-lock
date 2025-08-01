#!/bin/bash

set -e

echo "=== Testing conda-lock transitive dependency bug reproducer ==="

# Step 1: Create initial lockfile
echo "Step 1: Creating initial lockfile from environment-v1.yml"
conda-lock -f environment-v1.yml --lockfile conda-lock.yml

echo "Initial lockfile created. Checking for any immediate issues..."
if [ -f conda-lock.yml ]; then
    echo "✓ Initial lockfile created successfully"
else
    echo "✗ Failed to create initial lockfile"
    exit 1
fi

# Step 2: Update lockfile with new environment
echo ""
echo "Step 2: Updating lockfile with environment-v2.yml"
conda-lock -f environment-v2.yml --lockfile conda-lock.yml

echo "Updated lockfile. Checking for the bug..."

# Step 3: Check if the bug occurred
if [ -f outputv2.json ]; then
    echo "✓ outputv2.json generated - checking for empty categories..."
    
    # Look for packages with empty categories
    if grep -q '"categories": \[\]' outputv2.json; then
        echo "✗ BUG FOUND: Found packages with empty categories in outputv2.json"
        echo "Packages with empty categories:"
        grep -B 2 -A 2 '"categories": \[\]' outputv2.json
    else
        echo "✓ No empty categories found in outputv2.json"
    fi
else
    echo "✗ outputv2.json not found"
fi

if [ -f outputv1.json ]; then
    echo "✓ outputv1.json generated"
else
    echo "✗ outputv1.json not found"
fi

echo ""
echo "=== Reproducer test completed ==="