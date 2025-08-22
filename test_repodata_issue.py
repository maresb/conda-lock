#!/usr/bin/env python3
"""
Test script to reproduce the repodata_record.json issue with mamba.

This script demonstrates the problem where mamba writes incomplete metadata
to repodata_record.json when installing from explicit lockfiles.
"""

import json
import os
import subprocess
import tempfile
import pathlib
import shutil
import sys
from typing import Dict, Any


def create_test_lockfile() -> str:
    """Create a minimal test lockfile with the problematic package."""
    lockfile_content = """@EXPLICIT
https://conda.anaconda.org/conda-forge/noarch/ipykernel-6.30.1-pyh82676e8_0.conda#b0cc25825ce9212b8bee37829abad4d6
"""
    return lockfile_content


def check_micromamba_version() -> str:
    """Check the installed micromamba version."""
    try:
        result = subprocess.run(
            ["micromamba", "--version"], 
            capture_output=True, 
            text=True, 
            check=True
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "micromamba not found"


def install_package(lockfile_path: str) -> bool:
    """Install the package using the lockfile."""
    try:
        subprocess.run(
            ["micromamba", "install", "--yes", "--file", lockfile_path],
            check=True,
            capture_output=True
        )
        return True
    except subprocess.CalledProcessError as e:
        print(f"Installation failed: {e}")
        print(f"STDOUT: {e.stdout}")
        print(f"STDERR: {e.stderr}")
        return False


def find_package_cache() -> pathlib.Path:
    """Find the micromamba package cache directory."""
    try:
        result = subprocess.run(
            ["micromamba", "config", "--json", "list", "pkgs_dirs"],
            capture_output=True,
            text=True,
            check=True
        )
        config = json.loads(result.stdout)
        pkgs_dirs = config.get("pkgs_dirs", [])
        if pkgs_dirs:
            return pathlib.Path(pkgs_dirs[0])
        else:
            raise ValueError("No package cache directories found")
    except Exception as e:
        print(f"Failed to get package cache: {e}")
        # Fallback to common locations
        fallback_paths = [
            pathlib.Path.home() / ".conda" / "pkgs",
            pathlib.Path("/opt/conda/pkgs"),
        ]
        for path in fallback_paths:
            if path.exists():
                return path
        raise ValueError("Could not determine package cache location")


def read_repodata_record(pkgs_dir: pathlib.Path, package_name: str) -> Dict[str, Any]:
    """Read the repodata_record.json for a specific package."""
    package_dir = pkgs_dir / package_name
    repodata_file = package_dir / "info" / "repodata_record.json"
    
    if not repodata_file.exists():
        raise FileNotFoundError(f"repodata_record.json not found at {repodata_file}")
    
    with open(repodata_file) as f:
        return json.load(f)


def analyze_metadata(metadata: Dict[str, Any]) -> Dict[str, Any]:
    """Analyze the metadata for potential issues."""
    issues = {}
    
    # Check for empty depends list
    if metadata.get("depends") == []:
        issues["empty_depends"] = "depends list is empty (should contain dependencies)"
    
    # Check for zero timestamp
    if metadata.get("timestamp") == 0:
        issues["zero_timestamp"] = "timestamp is 0 (should be actual timestamp)"
    
    # Check for missing sha256
    if "sha256" not in metadata:
        issues["missing_sha256"] = "sha256 field is missing"
    
    # Check for empty license
    if metadata.get("license") == "":
        issues["empty_license"] = "license field is empty"
    
    return issues


def main():
    """Main test function."""
    print("=== Mamba Repodata Record Issue Test ===\n")
    
    # Check micromamba version
    version = check_micromamba_version()
    print(f"Micromamba version: {version}")
    
    # Create test lockfile
    with tempfile.NamedTemporaryFile(mode='w', suffix='.lock', delete=False) as f:
        lockfile_content = create_test_lockfile()
        f.write(lockfile_content)
        lockfile_path = f.name
    
    print(f"Created test lockfile: {lockfile_path}")
    print(f"Lockfile contents:\n{lockfile_content}")
    
    try:
        # Install the package
        print("\nInstalling package...")
        if not install_package(lockfile_path):
            print("Installation failed, cannot continue test")
            return
        
        print("Package installed successfully")
        
        # Find package cache
        pkgs_dir = find_package_cache()
        print(f"Package cache: {pkgs_dir}")
        
        # Read repodata_record.json
        package_name = "ipykernel-6.30.1-pyh82676e8_0"
        print(f"\nReading metadata for package: {package_name}")
        
        try:
            metadata = read_repodata_record(pkgs_dir, package_name)
            print("Metadata loaded successfully")
            
            # Analyze for issues
            issues = analyze_metadata(metadata)
            
            if issues:
                print("\n=== ISSUES FOUND ===")
                for issue_type, description in issues.items():
                    print(f"❌ {issue_type}: {description}")
                
                print("\n=== FULL METADATA ===")
                print(json.dumps(metadata, indent=2))
                
                print("\n=== EXPECTED BEHAVIOR ===")
                print("The depends list should contain the actual dependencies:")
                print("- __linux")
                print("- comm >=0.1.1")
                print("- debugpy >=1.6.5")
                print("- ipython >=7.23.1")
                print("- jupyter_client >=8.0.0")
                print("- jupyter_core >=4.12,!=5.0.*")
                print("- matplotlib-inline >=0.1")
                print("- nest-asyncio >=1.4")
                print("- packaging >=22")
                print("- psutil >=5.7")
                print("- python >=3.9")
                print("- pyzmq >=25")
                print("- tornado >=6.2")
                print("- traitlets >=5.4.0")
                
                print("\nThe timestamp should be a real timestamp, not 0")
                print("The sha256 field should be present")
                
            else:
                print("✅ No issues found - metadata looks correct")
                
        except FileNotFoundError as e:
            print(f"Failed to read metadata: {e}")
            print("This might indicate the package wasn't installed correctly")
            
    finally:
        # Cleanup
        try:
            os.unlink(lockfile_path)
        except:
            pass


if __name__ == "__main__":
    main()