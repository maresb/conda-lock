#!/bin/bash

set -e

echo "=== Attempting to trigger validation error ==="

# Create a simple environment
cat > test-env.yml << 'EOF'
name: test
channels:
  - conda-forge
dependencies:
  - python=3.9
  - numpy
  - scikit-learn
EOF

# Create initial lockfile
echo "Step 1: Creating initial lockfile..."
conda-lock -f test-env.yml --lockfile test-lock.yml -p linux-64

# Try to update with a different environment that might cause issues
echo "Step 2: Updating with different environment..."
conda-lock -f test-env.yml --lockfile test-lock.yml -p linux-64 --update numpy

# Check if any output files were generated
echo "Step 3: Checking for output files..."
if [ -f outputv2.json ]; then
    echo "✓ outputv2.json found"
    if grep -q '"categories": \[\]' outputv2.json; then
        echo "✗ BUG FOUND: Empty categories detected"
        grep -B 2 -A 2 '"categories": \[\]' outputv2.json
    else
        echo "✓ No empty categories found"
    fi
else
    echo "✗ outputv2.json not found"
fi

# Try to install from the lockfile to see if it triggers validation
echo "Step 4: Testing lockfile installation..."
if conda-lock install --name test-env-install test-lock.yml 2>&1 | grep -q "InconsistentCondaDependencies"; then
    echo "✗ BUG FOUND: InconsistentCondaDependencies exception triggered"
else
    echo "✓ No validation errors found"
fi

echo "=== Validation error test completed ==="