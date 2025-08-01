#!/bin/bash

set -e

echo "=== Mathematical conda-lock empty categories reproducer ==="

# Step 1: Create environment with package that has specific transitive dependencies
cat > env-step1.yml << 'EOF'
name: test
channels:
  - conda-forge
dependencies:
  - python=3.9
  - scikit-learn  # depends on numpy, scipy, joblib, etc.
EOF

# Step 2: Update to environment that removes scikit-learn but adds packages with overlapping deps
cat > env-step2.yml << 'EOF'
name: test
channels:
  - conda-forge
dependencies:
  - python=3.9
  - matplotlib  # depends on numpy, but different version constraints
  - seaborn     # depends on numpy, pandas, matplotlib
EOF

# Step 3: Update to environment that adds back scikit-learn with different version
cat > env-step3.yml << 'EOF'
name: test
channels:
  - conda-forge
dependencies:
  - python=3.9
  - matplotlib
  - seaborn
  - scikit-learn  # might bring in different versions of numpy/scipy
EOF

echo "Step 1: Creating initial environment with scikit-learn..."
conda-lock -f env-step1.yml --lockfile test-lock.yml -p linux-64

echo "Step 2: Updating to environment without scikit-learn..."
conda-lock -f env-step2.yml --lockfile test-lock.yml -p linux-64

echo "Step 3: Updating to environment with scikit-learn again..."
conda-lock -f env-step3.yml --lockfile test-lock.yml -p linux-64

echo "Step 4: Checking for empty categories..."
if [ -f outputv2.json ]; then
    echo "✓ outputv2.json found"
    if grep -q '"categories": \[\]' outputv2.json; then
        echo "✗ BUG FOUND: Empty categories detected"
        echo "Packages with empty categories:"
        grep -B 2 -A 2 '"categories": \[\]' outputv2.json
        
        # Analyze the specific packages
        echo ""
        echo "Detailed analysis:"
        python3 -c "
import json
with open('outputv2.json', 'r') as f:
    data = json.load(f)

# Find packages with empty categories
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

print(f'Found {len(empty_cat_packages)} packages with empty categories:')
for pkg in empty_cat_packages:
    print(f'  - {pkg[\"name\"]} {pkg[\"version\"]} ({pkg[\"manager\"]}, {pkg[\"platform\"]})')
    if pkg['dependencies']:
        print(f'    Dependencies: {pkg[\"dependencies\"]}')

# Find packages that depend on empty-category packages
print('\nPackages that depend on empty-category packages:')
for pkg in data.get('package', []):
    deps = pkg.get('dependencies', [])
    empty_deps = [dep for dep in deps if any(ep['name'] == dep for ep in empty_cat_packages)]
    if empty_deps:
        print(f'  - {pkg[\"name\"]} depends on: {empty_deps}')
"
    else
        echo "✓ No empty categories found"
    fi
else
    echo "✗ outputv2.json not found"
fi

echo "=== Mathematical reproducer completed ==="