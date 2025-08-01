#!/bin/bash

set -e

echo "=== Concrete conda-lock transitive dependency bug reproducer ==="

# Step 1: Create initial environment with minimal dependencies
cat > env-v1.yml << 'EOF'
name: test
channels:
  - conda-forge
dependencies:
  - python=3.9
  - numpy
EOF

# Step 2: Create updated environment with dependencies that have complex transitive chains
cat > env-v2.yml << 'EOF'
name: test
channels:
  - conda-forge
dependencies:
  - python=3.9
  - numpy
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
EOF

echo "Step 1: Creating initial lockfile..."
conda-lock -f env-v1.yml --lockfile conda-lock.yml -p linux-64

echo "Step 2: Updating with complex environment..."
conda-lock -f env-v2.yml --lockfile conda-lock.yml -p linux-64

echo "Step 3: Checking for output files and analyzing..."

if [ -f outputv2.json ]; then
    echo "✓ outputv2.json found - analyzing for empty categories..."
    
    # Look for packages with empty categories
    if grep -q '"categories": \[\]' outputv2.json; then
        echo "✗ BUG FOUND: Found packages with empty categories in outputv2.json"
        echo "Packages with empty categories:"
        grep -B 2 -A 2 '"categories": \[\]' outputv2.json
        
        # Get specific package names with empty categories
        echo ""
        echo "Specific packages with empty categories:"
        python3 -c "
import json
with open('outputv2.json', 'r') as f:
    data = json.load(f)

empty_cat_packages = []
for pkg in data.get('package', []):
    if pkg.get('categories') == []:
        empty_cat_packages.append({
            'name': pkg['name'],
            'manager': pkg.get('manager', 'unknown'),
            'platform': pkg.get('platform', 'unknown'),
            'dependencies': pkg.get('dependencies', [])
        })

print(f'Found {len(empty_cat_packages)} packages with empty categories:')
for pkg in empty_cat_packages:
    print(f'  - {pkg[\"name\"]} ({pkg[\"manager\"]}, {pkg[\"platform\"]})')
    if pkg['dependencies']:
        print(f'    Dependencies: {pkg[\"dependencies\"]}')
"
    else
        echo "✓ No empty categories found in outputv2.json"
    fi
else
    echo "✗ outputv2.json not found"
fi

if [ -f outputv1.json ]; then
    echo "✓ outputv1.json found"
else
    echo "✗ outputv1.json not found"
fi

echo ""
echo "=== Concrete reproducer completed ==="