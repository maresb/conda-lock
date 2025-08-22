"""
Metadata validation and fallback handling for conda-lock.

This module provides robust handling of incomplete metadata that can occur
when mamba writes incomplete repodata_record.json files, particularly
when installing from explicit lockfiles.
"""

import json
import logging
import pathlib
import subprocess
import tempfile
import zipfile
from typing import Dict, Any, Optional, Tuple
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class MetadataValidationError(Exception):
    """Raised when metadata validation fails and no fallback is available."""
    pass


class IncompleteMetadataError(Exception):
    """Raised when metadata is incomplete but potentially recoverable."""
    
    def __init__(self, message: str, metadata: Dict[str, Any], issues: Dict[str, str]):
        super().__init__(message)
        self.metadata = metadata
        self.issues = issues


def validate_metadata(metadata: Dict[str, Any]) -> Tuple[bool, Dict[str, str]]:
    """
    Validate that metadata contains all required fields with valid values.
    
    Returns:
        Tuple of (is_valid, issues_dict)
    """
    issues = {}
    
    # Check for empty depends list (critical for conda-lock)
    if metadata.get("depends") == []:
        issues["empty_depends"] = "depends list is empty (should contain actual dependencies)"
    
    # Check for zero timestamp
    if metadata.get("timestamp") == 0:
        issues["zero_timestamp"] = "timestamp is 0 (should be actual timestamp)"
    
    # Check for missing sha256
    if "sha256" not in metadata:
        issues["missing_sha256"] = "sha256 field is missing"
    
    # Check for empty license
    if metadata.get("license") == "":
        issues["empty_license"] = "license field is empty"
    
    # Check for missing critical fields
    required_fields = ["name", "version", "channel", "subdir", "url"]
    for field in required_fields:
        if not metadata.get(field):
            issues[f"missing_{field}"] = f"required field '{field}' is missing or empty"
    
    is_valid = len(issues) == 0
    return is_valid, issues


def extract_metadata_from_conda_package(package_path: pathlib.Path) -> Optional[Dict[str, Any]]:
    """
    Extract metadata from a .conda package file.
    
    This is a fallback method when repodata_record.json is incomplete.
    """
    try:
        if not package_path.exists():
            return None
            
        with zipfile.ZipFile(package_path, 'r') as zf:
            # Look for metadata files in the package
            metadata_files = [
                'info/repodata_record.json',
                'info/index.json',
                'info/about.json'
            ]
            
            for metadata_file in metadata_files:
                if metadata_file in zf.namelist():
                    try:
                        with zf.open(metadata_file) as f:
                            data = json.load(f)
                            if metadata_file == 'info/repodata_record.json':
                                return data
                            elif metadata_file == 'info/index.json':
                                # Convert index.json format to repodata_record.json format
                                return _convert_index_to_repodata(data)
                    except (json.JSONDecodeError, KeyError):
                        continue
            
            return None
    except Exception as e:
        logger.debug(f"Failed to extract metadata from package {package_path}: {e}")
        return None


def _convert_index_to_repodata(index_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert index.json format to repodata_record.json format.
    
    This is needed because some packages only have index.json, not repodata_record.json.
    """
    # Map common fields
    repodata = {
        "name": index_data.get("name", ""),
        "version": index_data.get("version", ""),
        "build": index_data.get("build", ""),
        "build_number": index_data.get("build_number", 0),
        "depends": index_data.get("depends", []),
        "constrains": index_data.get("constrains", []),
        "channel": index_data.get("channel", ""),
        "subdir": index_data.get("subdir", ""),
        "url": index_data.get("url", ""),
        "fn": index_data.get("fn", ""),
        "license": index_data.get("license", ""),
        "license_family": index_data.get("license_family", ""),
        "md5": index_data.get("md5", ""),
        "sha256": index_data.get("sha256", ""),
        "size": index_data.get("size", 0),
        "timestamp": index_data.get("timestamp", 0),
        "track_features": index_data.get("track_features", ""),
        "noarch": index_data.get("noarch", ""),
        "platform": index_data.get("platform", ""),
        "arch": index_data.get("arch", ""),
    }
    
    return repodata


def fetch_metadata_from_url(url: str) -> Optional[Dict[str, Any]]:
    """
    Fetch metadata from the package URL as a last resort.
    
    This is the least reliable method but can provide some metadata
    when all other methods fail.
    """
    try:
        # Use curl to fetch the package and extract basic info
        # This is a fallback method that may not work for all packages
        result = subprocess.run(
            ["curl", "-s", "-I", url],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode == 0:
            # Extract basic information from headers
            headers = result.stdout
            metadata = {
                "url": url,
                "depends": [],  # We can't extract this from headers
                "timestamp": 0,  # We can't extract this from headers
                "sha256": "",    # We can't extract this from headers
            }
            
            # Try to extract filename from URL
            parsed_url = urlparse(url)
            if parsed_url.path:
                metadata["fn"] = parsed_url.path.split("/")[-1]
            
            return metadata
    except Exception as e:
        logger.debug(f"Failed to fetch metadata from URL {url}: {e}")
    
    return None


def get_robust_metadata(
    pkgs_dir: pathlib.Path,
    dist_name: str,
    fallback_url: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get metadata for a package with robust fallback handling.
    
    This function tries multiple methods to get complete metadata:
    1. Read repodata_record.json
    2. Validate the metadata
    3. If incomplete, try to extract from the package file
    4. If still incomplete, try to fetch from URL (last resort)
    
    Args:
        pkgs_dir: Package cache directory
        dist_name: Distribution name (e.g., "ipykernel-6.30.1-pyh82676e8_0")
        fallback_url: Optional URL to use as fallback
        
    Returns:
        Complete metadata dictionary
        
    Raises:
        MetadataValidationError: If no valid metadata can be obtained
        IncompleteMetadataError: If metadata is incomplete but recoverable
    """
    # Method 1: Try to read repodata_record.json
    repodata_file = pkgs_dir / dist_name / "info" / "repodata_record.json"
    if repodata_file.exists():
        try:
            with open(repodata_file) as f:
                metadata = json.load(f)
            
            # Validate the metadata
            is_valid, issues = validate_metadata(metadata)
            
            if is_valid:
                logger.debug(f"Found valid metadata in repodata_record.json for {dist_name}")
                return metadata
            else:
                logger.warning(
                    f"repodata_record.json for {dist_name} has issues: {issues}. "
                    "Attempting fallback methods..."
                )
                
                # Store the incomplete metadata for potential recovery
                incomplete_metadata = metadata
                incomplete_issues = issues
        except Exception as e:
            logger.debug(f"Failed to read repodata_record.json for {dist_name}: {e}")
            incomplete_metadata = {}
            incomplete_issues = {}
    else:
        incomplete_metadata = {}
        incomplete_issues = {}
    
    # Method 2: Try to extract from the package file
    package_path = pkgs_dir / dist_name / f"{dist_name}.conda"
    if not package_path.exists():
        package_path = pkgs_dir / dist_name / f"{dist_name}.tar.bz2"
    
    if package_path.exists():
        extracted_metadata = extract_metadata_from_conda_package(package_path)
        if extracted_metadata:
            is_valid, issues = validate_metadata(extracted_metadata)
            if is_valid:
                logger.info(f"Successfully extracted valid metadata from package file for {dist_name}")
                return extracted_metadata
            else:
                logger.debug(f"Package file metadata also has issues: {issues}")
    
    # Method 3: Try to fetch from URL (last resort)
    if fallback_url:
        url_metadata = fetch_metadata_from_url(fallback_url)
        if url_metadata:
            # Merge with any existing metadata we have
            merged_metadata = {**incomplete_metadata, **url_metadata}
            is_valid, issues = validate_metadata(merged_metadata)
            if is_valid:
                logger.info(f"Successfully obtained metadata from URL for {dist_name}")
                return merged_metadata
    
    # If we get here, we couldn't get valid metadata
    if incomplete_metadata:
        raise IncompleteMetadataError(
            f"Unable to obtain complete metadata for {dist_name}. "
            "The repodata_record.json file appears to be incomplete due to a known "
            "mamba issue when installing from explicit lockfiles.",
            incomplete_metadata,
            incomplete_issues
        )
    else:
        raise MetadataValidationError(
            f"Unable to obtain any metadata for {dist_name}. "
            "This may indicate a corrupted package or missing files."
        )


def suggest_fix_for_incomplete_metadata(dist_name: str, issues: Dict[str, str]) -> str:
    """
    Generate a helpful suggestion for fixing incomplete metadata.
    """
    suggestions = []
    
    if "empty_depends" in issues:
        suggestions.append(
            "The package dependencies are missing. This is a critical issue for conda-lock. "
            "Consider reinstalling the package or using a different mamba version."
        )
    
    if "zero_timestamp" in issues:
        suggestions.append(
            "The package timestamp is invalid. This may cause issues with dependency resolution."
        )
    
    if "missing_sha256" in issues:
        suggestions.append(
            "The package SHA256 hash is missing. This may affect package verification."
        )
    
    if suggestions:
        return f"Suggestions for {dist_name}:\n" + "\n".join(f"- {s}" for s in suggestions)
    else:
        return f"No specific suggestions available for {dist_name}."