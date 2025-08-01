#!/bin/bash

set -e

echo "=== Concrete Mathematical Empty Categories Reproducer ==="

# Step 1: Create environment with a package that has specific transitive dependencies
cat > env-math1.yml << 'EOF'
name: test
channels:
  - conda-forge
dependencies:
  - python=3.9
  - requests  # depends on urllib3, certifi, chardet, idna
EOF

# Step 2: Update to environment that removes requests but keeps some of its deps
cat > env-math2.yml << 'EOF'
name: test
channels:
  - conda-forge
dependencies:
  - python=3.9
  - urllib3  # was a transitive dep of requests, now direct
  - certifi  # was a transitive dep of requests, now direct
EOF

# Step 3: Update to environment that adds back requests
cat > env-math3.yml << 'EOF'
name: test
channels:
  - conda-forge
dependencies:
  - python=3.9
  - urllib3
  - certifi
  - requests  # might bring in different versions of its deps
EOF

echo "Step 1: Creating environment with requests..."
conda-lock -f env-math1.yml --lockfile math-lock.yml -p linux-64

echo "Step 2: Updating to environment without requests..."
conda-lock -f env-math2.yml --lockfile math-lock.yml -p linux-64

echo "Step 3: Updating to environment with requests again..."
conda-lock -f env-math3.yml --lockfile math-lock.yml -p linux-64

echo "Step 4: Analyzing lockfile for potential issues..."

# Check if the lockfile has any packages that might be orphaned
python3 -c "
import yaml
import sys

try:
    with open('math-lock.yml', 'r') as f:
        data = yaml.safe_load(f)
    
    packages = data.get('package', [])
    print(f'Total packages in lockfile: {len(packages)}')
    
    # Check for packages that might be orphaned
    orphaned = []
    for pkg in packages:
        name = pkg.get('name', '')
        category = pkg.get('category', '')
        deps = pkg.get('dependencies', {})
        
        # Look for packages that might be problematic
        if name in ['chardet', 'idna'] and category == 'main':
            orphaned.append({
                'name': name,
                'category': category,
                'dependencies': deps
            })
    
    if orphaned:
        print(f'Found {len(orphaned)} potentially orphaned packages:')
        for pkg in orphaned:
            print(f'  - {pkg[\"name\"]} (category: {pkg[\"category\"]})')
    else:
        print('No obvious orphaned packages found')
        
except Exception as e:
    print(f'Error analyzing lockfile: {e}')
"

echo "Step 5: Testing lockfile installation..."
if conda-lock install --name test-math-install math-lock.yml 2>&1 | grep -q "InconsistentCondaDependencies"; then
    echo "✗ BUG FOUND: InconsistentCondaDependencies exception triggered"
else
    echo "✓ No validation errors found"
fi

echo "=== Concrete mathematical reproducer completed ==="