"""
Tests for the metadata validator module.

This module tests the robust metadata handling that addresses the
repodata_record.json issue with mamba.
"""

import json
import pathlib
import tempfile
import zipfile
from unittest.mock import Mock, patch, mock_open

import pytest

from conda_lock.metadata_validator import (
    validate_metadata,
    extract_metadata_from_conda_package,
    _convert_index_to_repodata,
    fetch_metadata_from_url,
    get_robust_metadata,
    suggest_fix_for_incomplete_metadata,
    MetadataValidationError,
    IncompleteMetadataError,
)


class TestValidateMetadata:
    """Test metadata validation functionality."""
    
    def test_valid_metadata(self):
        """Test that valid metadata passes validation."""
        metadata = {
            "name": "test-package",
            "version": "1.0.0",
            "build": "py_0",
            "depends": ["python >=3.8"],
            "channel": "conda-forge",
            "subdir": "noarch",
            "url": "https://example.com/test-package-1.0.0-py_0.conda",
            "timestamp": 1234567890,
            "sha256": "abc123",
            "license": "MIT",
        }
        
        is_valid, issues = validate_metadata(metadata)
        assert is_valid
        assert len(issues) == 0
    
    def test_empty_depends_list(self):
        """Test that empty depends list is detected."""
        metadata = {
            "name": "test-package",
            "version": "1.0.0",
            "depends": [],
            "channel": "conda-forge",
            "subdir": "noarch",
            "url": "https://example.com/test-package-1.0.0-py_0.conda",
        }
        
        is_valid, issues = validate_metadata(metadata)
        assert not is_valid
        assert "empty_depends" in issues
    
    def test_zero_timestamp(self):
        """Test that zero timestamp is detected."""
        metadata = {
            "name": "test-package",
            "version": "1.0.0",
            "depends": ["python >=3.8"],
            "channel": "conda-forge",
            "subdir": "noarch",
            "url": "https://example.com/test-package-1.0.0-py_0.conda",
            "timestamp": 0,
        }
        
        is_valid, issues = validate_metadata(metadata)
        assert not is_valid
        assert "zero_timestamp" in issues
    
    def test_missing_sha256(self):
        """Test that missing sha256 is detected."""
        metadata = {
            "name": "test-package",
            "version": "1.0.0",
            "depends": ["python >=3.8"],
            "channel": "conda-forge",
            "subdir": "noarch",
            "url": "https://example.com/test-package-1.0.0-py_0.conda",
        }
        
        is_valid, issues = validate_metadata(metadata)
        assert not is_valid
        assert "missing_sha256" in issues
    
    def test_empty_license(self):
        """Test that empty license is detected."""
        metadata = {
            "name": "test-package",
            "version": "1.0.0",
            "depends": ["python >=3.8"],
            "channel": "conda-forge",
            "subdir": "noarch",
            "url": "https://example.com/test-package-1.0.0-py_0.conda",
            "license": "",
        }
        
        is_valid, issues = validate_metadata(metadata)
        assert not is_valid
        assert "empty_license" in issues
    
    def test_multiple_issues(self):
        """Test that multiple issues are detected."""
        metadata = {
            "name": "test-package",
            "version": "1.0.0",
            "depends": [],
            "channel": "conda-forge",
            "subdir": "noarch",
            "url": "https://example.com/test-package-1.0.0-py_0.conda",
            "timestamp": 0,
            "license": "",
        }
        
        is_valid, issues = validate_metadata(metadata)
        assert not is_valid
        assert len(issues) == 3
        assert "empty_depends" in issues
        assert "zero_timestamp" in issues
        assert "empty_license" in issues


class TestExtractMetadataFromCondaPackage:
    """Test conda package metadata extraction."""
    
    def test_extract_from_repodata_record(self):
        """Test extraction from repodata_record.json in package."""
        metadata = {
            "name": "test-package",
            "version": "1.0.0",
            "depends": ["python >=3.8"],
        }
        
        with tempfile.NamedTemporaryFile(suffix='.conda', delete=False) as f:
            with zipfile.ZipFile(f.name, 'w') as zf:
                zf.writestr('info/repodata_record.json', json.dumps(metadata))
            
            try:
                result = extract_metadata_from_conda_package(pathlib.Path(f.name))
                assert result == metadata
            finally:
                pathlib.Path(f.name).unlink()
    
    def test_extract_from_index_json(self):
        """Test extraction from index.json in package."""
        index_data = {
            "name": "test-package",
            "version": "1.0.0",
            "depends": ["python >=3.8"],
            "build": "py_0",
            "channel": "conda-forge",
        }
        
        with tempfile.NamedTemporaryFile(suffix='.conda', delete=False) as f:
            with zipfile.ZipFile(f.name, 'w') as zf:
                zf.writestr('info/index.json', json.dumps(index_data))
            
            try:
                result = extract_metadata_from_conda_package(pathlib.Path(f.name))
                assert result["name"] == "test-package"
                assert result["version"] == "1.0.0"
                assert result["depends"] == ["python >=3.8"]
            finally:
                pathlib.Path(f.name).unlink()
    
    def test_package_not_found(self):
        """Test handling of non-existent package."""
        result = extract_metadata_from_conda_package(pathlib.Path("/nonexistent/package.conda"))
        assert result is None
    
    def test_invalid_zip_file(self):
        """Test handling of invalid zip file."""
        with tempfile.NamedTemporaryFile(suffix='.conda', delete=False) as f:
            f.write(b"not a zip file")
            f.flush()
            
            try:
                result = extract_metadata_from_conda_package(pathlib.Path(f.name))
                assert result is None
            finally:
                pathlib.Path(f.name).unlink()


class TestConvertIndexToRepodata:
    """Test conversion from index.json to repodata_record.json format."""
    
    def test_basic_conversion(self):
        """Test basic field mapping."""
        index_data = {
            "name": "test-package",
            "version": "1.0.0",
            "build": "py_0",
            "depends": ["python >=3.8"],
            "channel": "conda-forge",
            "subdir": "noarch",
            "url": "https://example.com/test-package-1.0.0-py_0.conda",
            "fn": "test-package-1.0.0-py_0.conda",
            "license": "MIT",
            "md5": "abc123",
            "sha256": "def456",
        }
        
        result = _convert_index_to_repodata(index_data)
        
        assert result["name"] == "test-package"
        assert result["version"] == "1.0.0"
        assert result["depends"] == ["python >=3.8"]
        assert result["channel"] == "conda-forge"
        assert result["subdir"] == "noarch"
        assert result["url"] == "https://example.com/test-package-1.0.0-py_0.conda"
        assert result["fn"] == "test-package-1.0.0-py_0.conda"
        assert result["license"] == "MIT"
        assert result["md5"] == "abc123"
        assert result["sha256"] == "def456"
    
    def test_missing_fields(self):
        """Test handling of missing fields."""
        index_data = {
            "name": "test-package",
            "version": "1.0.0",
        }
        
        result = _convert_index_to_repodata(index_data)
        
        assert result["name"] == "test-package"
        assert result["version"] == "1.0.0"
        assert result["depends"] == []
        assert result["channel"] == ""
        assert result["subdir"] == ""


class TestFetchMetadataFromUrl:
    """Test URL-based metadata fetching."""
    
    @patch('subprocess.run')
    def test_successful_fetch(self, mock_run):
        """Test successful metadata fetch from URL."""
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "HTTP/1.1 200 OK\nContent-Length: 12345\n"
        
        result = fetch_metadata_from_url("https://example.com/package.conda")
        
        assert result is not None
        assert result["url"] == "https://example.com/package.conda"
        assert result["fn"] == "package.conda"
    
    @patch('subprocess.run')
    def test_failed_fetch(self, mock_run):
        """Test failed metadata fetch from URL."""
        mock_run.return_value.returncode = 1
        
        result = fetch_metadata_from_url("https://example.com/package.conda")
        
        assert result is None
    
    @patch('subprocess.run')
    def test_timeout(self, mock_run):
        """Test timeout handling."""
        mock_run.side_effect = subprocess.TimeoutExpired("curl", 30)
        
        result = fetch_metadata_from_url("https://example.com/package.conda")
        
        assert result is None


class TestGetRobustMetadata:
    """Test the main robust metadata retrieval function."""
    
    @patch('pathlib.Path.exists')
    @patch('builtins.open', new_callable=mock_open)
    def test_valid_repodata_record(self, mock_file, mock_exists):
        """Test successful retrieval from valid repodata_record.json."""
        mock_exists.return_value = True
        
        valid_metadata = {
            "name": "test-package",
            "version": "1.0.0",
            "depends": ["python >=3.8"],
            "channel": "conda-forge",
            "subdir": "noarch",
            "url": "https://example.com/test-package-1.0.0-py_0.conda",
            "timestamp": 1234567890,
            "sha256": "abc123",
        }
        
        mock_file.return_value.__enter__.return_value.read.return_value = json.dumps(valid_metadata)
        
        with patch('conda_lock.metadata_validator.validate_metadata') as mock_validate:
            mock_validate.return_value = (True, {})
            
            result = get_robust_metadata(
                pathlib.Path("/tmp/pkgs"),
                "test-package-1.0.0-py_0"
            )
            
            assert result == valid_metadata
    
    @patch('pathlib.Path.exists')
    @patch('builtins.open', new_callable=mock_open)
    def test_incomplete_repodata_record(self, mock_file, mock_exists):
        """Test fallback when repodata_record.json is incomplete."""
        mock_exists.return_value = True
        
        incomplete_metadata = {
            "name": "test-package",
            "version": "1.0.0",
            "depends": [],
            "channel": "conda-forge",
            "subdir": "noarch",
            "url": "https://example.com/test-package-1.0.0-py_0.conda",
            "timestamp": 0,
        }
        
        mock_file.return_value.__enter__.return_value.read.return_value = json.dumps(incomplete_metadata)
        
        with patch('conda_lock.metadata_validator.validate_metadata') as mock_validate:
            mock_validate.return_value = (False, {"empty_depends": "depends list is empty"})
            
            with patch('conda_lock.metadata_validator.extract_metadata_from_conda_package') as mock_extract:
                mock_extract.return_value = None
                
                with pytest.raises(IncompleteMetadataError) as exc_info:
                    get_robust_metadata(
                        pathlib.Path("/tmp/pkgs"),
                        "test-package-1.0.0-py_0"
                    )
                
                assert "depends list is empty" in str(exc_info.value.issues)
    
    @patch('pathlib.Path.exists')
    def test_package_file_fallback(self, mock_exists):
        """Test successful fallback to package file extraction."""
        # repodata_record.json doesn't exist
        mock_exists.side_effect = lambda path: "repodata_record.json" not in str(path)
        
        valid_metadata = {
            "name": "test-package",
            "version": "1.0.0",
            "depends": ["python >=3.8"],
            "channel": "conda-forge",
            "subdir": "noarch",
            "url": "https://example.com/test-package-1.0.0-py_0.conda",
            "timestamp": 1234567890,
            "sha256": "abc123",
        }
        
        with patch('conda_lock.metadata_validator.extract_metadata_from_conda_package') as mock_extract:
            mock_extract.return_value = valid_metadata
            
            with patch('conda_lock.metadata_validator.validate_metadata') as mock_validate:
                mock_validate.return_value = (True, {})
                
                result = get_robust_metadata(
                    pathlib.Path("/tmp/pkgs"),
                    "test-package-1.0.0-py_0"
                )
                
                assert result == valid_metadata


class TestSuggestFixForIncompleteMetadata:
    """Test suggestion generation for incomplete metadata."""
    
    def test_empty_depends_suggestion(self):
        """Test suggestion for empty depends list."""
        issues = {"empty_depends": "depends list is empty"}
        
        suggestion = suggest_fix_for_incomplete_metadata("test-package", issues)
        
        assert "dependencies are missing" in suggestion
        assert "critical issue for conda-lock" in suggestion
    
    def test_zero_timestamp_suggestion(self):
        """Test suggestion for zero timestamp."""
        issues = {"zero_timestamp": "timestamp is 0"}
        
        suggestion = suggest_fix_for_incomplete_metadata("test-package", issues)
        
        assert "timestamp is invalid" in suggestion
        assert "dependency resolution" in suggestion
    
    def test_missing_sha256_suggestion(self):
        """Test suggestion for missing sha256."""
        issues = {"missing_sha256": "sha256 field is missing"}
        
        suggestion = suggest_fix_for_incomplete_metadata("test-package", issues)
        
        assert "SHA256 hash is missing" in suggestion
        assert "package verification" in suggestion
    
    def test_multiple_issues_suggestions(self):
        """Test suggestions for multiple issues."""
        issues = {
            "empty_depends": "depends list is empty",
            "zero_timestamp": "timestamp is 0",
            "missing_sha256": "sha256 field is missing"
        }
        
        suggestion = suggest_fix_for_incomplete_metadata("test-package", issues)
        
        assert "dependencies are missing" in suggestion
        assert "timestamp is invalid" in suggestion
        assert "SHA256 hash is missing" in suggestion
    
    def test_no_suggestions(self):
        """Test handling when no specific suggestions are available."""
        issues = {"unknown_issue": "some unknown problem"}
        
        suggestion = suggest_fix_for_incomplete_metadata("test-package", issues)
        
        assert "No specific suggestions available" in suggestion


class TestIntegration:
    """Integration tests for the complete metadata handling workflow."""
    
    def test_real_world_scenario(self):
        """Test a realistic scenario with incomplete metadata."""
        # This simulates the actual issue described in the problem
        incomplete_metadata = {
            "arch": None,
            "build": "pyh82676e8_0",
            "build_number": 0,
            "build_string": "pyh82676e8_0",
            "channel": "conda-forge",
            "constrains": [],
            "depends": [],  # This is the problematic empty list
            "fn": "ipykernel-6.30.1-pyh82676e8_0.conda",
            "license": "",
            "license_family": "BSD",
            "md5": "b0cc25825ce9212b8bee37829abad4d6",
            "name": "ipykernel",
            "noarch": "python",
            "platform": None,
            "size": 121367,
            "subdir": "noarch",
            "timestamp": 0,  # This is the problematic zero timestamp
            "track_features": "",
            "url": "https://conda.anaconda.org/conda-forge/noarch/ipykernel-6.30.1-pyh82676e8_0.conda",
            "version": "6.30.1"
        }
        
        # Validate the metadata - it should fail
        is_valid, issues = validate_metadata(incomplete_metadata)
        assert not is_valid
        assert "empty_depends" in issues
        assert "zero_timestamp" in issues
        assert "missing_sha256" in issues
        assert "empty_license" in issues
        
        # Generate suggestions
        suggestion = suggest_fix_for_incomplete_metadata("ipykernel-6.30.1-pyh82676e8_0", issues)
        assert "dependencies are missing" in suggestion
        assert "critical issue for conda-lock" in suggestion