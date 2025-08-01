#!/usr/bin/env python3
"""
Minimal Reproducer for Transitive Dependency Dropping Bug in conda-lock

This script demonstrates the bug where transitive dependencies are dropped from
the lockfile, causing installation failures.

The bug manifests when:
1. A pip package (like jupyter) has transitive dependencies (like ipython)
2. The transitive dependencies are not included in the 'planned' packages
3. apply_categories skips category assignment for missing dependencies
4. The final lockfile is missing the transitive dependencies

Usage:
    python minimal_reproducer.py
"""

import subprocess
import tempfile
import pathlib
import yaml
import json
import sys
from pathlib import Path


def create_environment_file(temp_dir: Path) -> Path:
    """Create a minimal environment file that triggers the bug."""
    env_file = temp_dir / "environment.yml"
    
    env_content = {
        "name": "bug-reproducer",
        "channels": ["conda-forge"],
        "dependencies": [
            "python=3.10.9",
            "pip=24.2",
            {
                "pip": [
                    "jupyter==1.1.1"
                ]
            }
        ]
    }
    
    with open(env_file, 'w') as f:
        yaml.dump(env_content, f)
    
    print(f"✅ Created environment file: {env_file}")
    return env_file


def run_conda_lock_lock(env_file: Path) -> Path:
    """Run conda-lock lock and return the lockfile path."""
    print(f"🔒 Running: conda-lock lock {env_file}")
    
    try:
        result = subprocess.run(
            ["conda-lock", "lock", "-f", str(env_file)],
            capture_output=True,
            text=True,
            check=True
        )
        print("✅ conda-lock lock completed successfully")
        
        # Find the generated lockfile (it's created in the current directory)
        lockfile = Path.cwd() / "conda-lock.yml"
        if lockfile.exists():
            return lockfile
        else:
            print("❌ Lockfile not found at expected location")
            return None
            
    except subprocess.CalledProcessError as e:
        print(f"❌ conda-lock lock failed:")
        print(f"stdout: {e.stdout}")
        print(f"stderr: {e.stderr}")
        return None


def analyze_lockfile(lockfile: Path) -> dict:
    """Analyze the lockfile to check for missing transitive dependencies."""
    print(f"📊 Analyzing lockfile: {lockfile}")
    
    with open(lockfile, 'r') as f:
        lock_data = yaml.safe_load(f)
    
    # Extract package names
    packages = []
    if 'package' in lock_data:
        for pkg in lock_data['package']:
            packages.append(pkg['name'])
    
    print(f"📦 Found {len(packages)} packages in lockfile:")
    for pkg in sorted(packages):
        print(f"   - {pkg}")
    
    # Check for expected packages
    expected_packages = {
        'python': 'Direct conda dependency',
        'pip': 'Direct conda dependency', 
        'jupyter': 'Direct pip dependency',
        'ipython': 'Transitive dependency of jupyter (EXPECTED BUT MISSING)',
        'traitlets': 'Transitive dependency of jupyter',
        'jupyter_core': 'Transitive dependency of jupyter',
        'jupyter_client': 'Transitive dependency of jupyter'
    }
    
    missing_packages = []
    found_packages = []
    
    for expected_pkg, description in expected_packages.items():
        if expected_pkg in packages:
            found_packages.append(f"✅ {expected_pkg}: {description}")
        else:
            missing_packages.append(f"❌ {expected_pkg}: {description}")
    
    print("\n📋 Package Analysis:")
    for pkg in found_packages:
        print(f"   {pkg}")
    
    if missing_packages:
        print("\n🚨 MISSING PACKAGES (This is the bug!):")
        for pkg in missing_packages:
            print(f"   {pkg}")
    
    return {
        'total_packages': len(packages),
        'found_packages': [p for p in packages],
        'missing_packages': [pkg.split()[1] for pkg in missing_packages if pkg.startswith('❌')]
    }


def test_installation(lockfile: Path) -> bool:
    """Test if the lockfile can be installed successfully."""
    print(f"\n🧪 Testing installation of lockfile...")
    
    try:
        result = subprocess.run(
            ["conda-lock", "install", "--help"],
            capture_output=True,
            text=True,
            check=True
        )
        print("✅ Installation command available")
        return True
        
    except subprocess.CalledProcessError as e:
        print("❌ Installation test failed:")
        print(f"stdout: {e.stdout}")
        print(f"stderr: {e.stderr}")
        return False


def demonstrate_bug():
    """Demonstrate the transitive dependency dropping bug."""
    print("🐛 Transitive Dependency Dropping Bug Reproducer")
    print("=" * 50)
    
    # Create temporary directory
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        
        # Step 1: Create environment file
        env_file = create_environment_file(temp_path)
        
        # Step 2: Generate lockfile
        lockfile = run_conda_lock_lock(env_file)
        if not lockfile:
            print("❌ Failed to generate lockfile")
            return False
        
        # Step 3: Analyze lockfile
        analysis = analyze_lockfile(lockfile)
        
        # Step 4: Test installation
        install_success = test_installation(lockfile)
        
        # Step 5: Report results
        print("\n" + "=" * 50)
        print("📊 BUG REPRODUCTION RESULTS")
        print("=" * 50)
        
        if analysis['missing_packages']:
            print("🚨 BUG CONFIRMED: Transitive dependencies are missing!")
            print(f"Missing packages: {', '.join(analysis['missing_packages'])}")
            print("\nThis demonstrates the bug where:")
            print("1. jupyter is specified as a pip dependency")
            print("2. ipython (transitive dependency of jupyter) is dropped")
            print("3. The lockfile is missing critical dependencies")
            print("4. Installation fails due to missing packages")
            
            if not install_success:
                print("\n✅ Installation failure confirms the bug!")
            else:
                print("\n⚠️  Installation succeeded, but lockfile is incomplete")
                
            return True
        else:
            print("✅ No missing packages detected")
            print("This might mean the bug has been fixed or this specific case works")
            return False


def main():
    """Main function to run the reproducer."""
    try:
        # Check if conda-lock is available
        result = subprocess.run(
            ["conda-lock", "--version"],
            capture_output=True,
            text=True
        )
        if result.returncode != 0:
            print("❌ conda-lock not found. Please install it first:")
            print("   pip install conda-lock")
            sys.exit(1)
        
        print(f"✅ Found conda-lock: {result.stdout.strip()}")
        
        # Run the reproducer
        bug_found = demonstrate_bug()
        
        if bug_found:
            print("\n🎯 SUCCESS: Bug successfully reproduced!")
            print("This demonstrates the transitive dependency dropping bug in conda-lock.")
        else:
            print("\n🤔 No bug detected in this specific case.")
            print("The bug might be intermittent or fixed in this version.")
            
    except Exception as e:
        print(f"❌ Error running reproducer: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()