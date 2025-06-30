"""
Test module to boost coverage for utility functions and classes
that were previously untested or under-tested.
"""

import json
import os
import pathlib
import tempfile
from unittest.mock import patch, MagicMock

import pytest

from conda_lock.errors import (
    CondaLockError,
    PlatformValidationError,
    MissingEnvVarError,
    ChannelAggregationError,
)
from conda_lock.common import (
    get_in,
    read_file,
    write_file,
    temporary_file_with_contents,
    read_json,
    ordered_union,
    relative_path,
    warn,
)
from conda_lock.click_helpers import OrderedGroup
from conda_lock.lookup import (
    pypi_name_to_conda_name,
    conda_name_to_pypi_name,
    _get_pypi_lookup,
    _get_conda_lookup,
)
from conda_lock.virtual_package import (
    VirtualPackage,
    FullVirtualPackage,
    _parse_virtual_package_spec,
)


class TestCondaLockErrors:
    """Test error classes for proper inheritance and instantiation."""
    
    def test_conda_lock_error_base_class(self):
        """Test the base CondaLockError class."""
        error = CondaLockError("Test error message")
        assert str(error) == "Test error message"
        assert isinstance(error, Exception)
    
    def test_platform_validation_error(self):
        """Test PlatformValidationError inherits from CondaLockError."""
        error = PlatformValidationError("Platform mismatch")
        assert str(error) == "Platform mismatch"
        assert isinstance(error, CondaLockError)
        assert isinstance(error, Exception)
    
    def test_missing_env_var_error(self):
        """Test MissingEnvVarError inherits from CondaLockError."""
        error = MissingEnvVarError("Missing environment variable")
        assert str(error) == "Missing environment variable"
        assert isinstance(error, CondaLockError)
        assert isinstance(error, Exception)
    
    def test_channel_aggregation_error(self):
        """Test ChannelAggregationError inherits from CondaLockError."""
        error = ChannelAggregationError("Cannot combine channels")
        assert str(error) == "Cannot combine channels"
        assert isinstance(error, CondaLockError)
        assert isinstance(error, Exception)


class TestCommonUtilities:
    """Test utility functions in common.py module."""
    
    def test_get_in_success(self):
        """Test get_in function with valid nested dictionary."""
        data = {"a": {"b": {"c": 42}}}
        result = get_in(["a", "b", "c"], data)
        assert result == 42
        
        result = get_in(["a", "b"], data)
        assert result == {"c": 42}
        
        result = get_in(["a"], data)
        assert result == {"b": {"c": 42}}
    
    def test_get_in_missing_key(self):
        """Test get_in function with missing keys."""
        data = {"a": {"b": {"c": 42}}}
        result = get_in(["a", "missing"], data)
        assert result is None
        
        result = get_in(["missing", "key"], data, default="default_value")
        assert result == "default_value"
    
    def test_get_in_empty_keys(self):
        """Test get_in function with empty key list."""
        data = {"a": {"b": {"c": 42}}}
        result = get_in([], data)
        assert result == data
    
    def test_get_in_type_error(self):
        """Test get_in function with type mismatches."""
        data = {"a": "not_a_dict"}
        result = get_in(["a", "b"], data)
        assert result is None
    
    def test_read_file(self):
        """Test read_file function."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as tmp:
            test_content = "Hello, World!\nSecond line."
            tmp.write(test_content)
            tmp.flush()
            
            try:
                result = read_file(tmp.name)
                assert result == test_content
                
                # Test with pathlib.Path
                result = read_file(pathlib.Path(tmp.name))
                assert result == test_content
            finally:
                os.unlink(tmp.name)
    
    def test_write_file(self):
        """Test write_file function."""
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.close()
            
            try:
                test_content = "Test content\nwith newlines"
                write_file(test_content, tmp.name)
                
                with open(tmp.name, "r") as f:
                    result = f.read()
                assert result == test_content
                
                # Test with pathlib.Path
                test_content2 = "Different content"
                write_file(test_content2, pathlib.Path(tmp.name))
                
                with open(tmp.name, "r") as f:
                    result = f.read()
                assert result == test_content2
            finally:
                os.unlink(tmp.name)
    
    def test_temporary_file_with_contents(self):
        """Test temporary_file_with_contents context manager."""
        test_content = "Temporary file content\nwith multiple lines"
        
        with temporary_file_with_contents(test_content) as temp_path:
            assert isinstance(temp_path, pathlib.Path)
            assert temp_path.exists()
            
            # Read the content back
            with open(temp_path, "r") as f:
                result = f.read()
            assert result == test_content
        
        # File should be cleaned up after context exit
        assert not temp_path.exists()
    
    def test_read_json(self):
        """Test read_json function."""
        test_data = {"key": "value", "number": 42, "nested": {"inner": True}}
        
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tmp:
            json.dump(test_data, tmp)
            tmp.flush()
            
            try:
                result = read_json(tmp.name)
                assert result == test_data
                
                # Test with pathlib.Path
                result = read_json(pathlib.Path(tmp.name))
                assert result == test_data
            finally:
                os.unlink(tmp.name)
    
    def test_ordered_union(self):
        """Test ordered_union function."""
        # Test with overlapping collections
        result = ordered_union([["a", "b", "c"], ["b", "c", "d"], ["c", "d", "e"]])
        assert result == ["a", "b", "c", "d", "e"]
        
        # Test with no overlap
        result = ordered_union([["a"], ["b"], ["c"]])
        assert result == ["a", "b", "c"]
        
        # Test with empty collections
        result = ordered_union([[], ["a", "b"], []])
        assert result == ["a", "b"]
        
        # Test with single collection
        result = ordered_union([["x", "y", "z"]])
        assert result == ["x", "y", "z"]
        
        # Test with duplicates in same collection
        result = ordered_union([["a", "a", "b", "b"]])
        assert result == ["a", "b"]
    
    def test_relative_path(self):
        """Test relative_path function."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = pathlib.Path(tmpdir)
            
            # Create some test directories
            source_dir = tmpdir_path / "source"
            target_dir = tmpdir_path / "target"
            nested_source = tmpdir_path / "nested" / "source"
            nested_target = tmpdir_path / "nested" / "target"
            
            source_dir.mkdir()
            target_dir.mkdir()
            nested_source.mkdir(parents=True)
            nested_target.mkdir(parents=True)
            
            # Test sibling directories
            result = relative_path(source_dir, target_dir)
            assert result == "../target"
            
            # Test nested directories
            result = relative_path(nested_source, nested_target)
            assert result == "../target"
            
            # Test parent to child
            result = relative_path(tmpdir_path, nested_source)
            assert result == "nested/source"
    
    def test_warn(self):
        """Test warn function."""
        with pytest.warns(UserWarning, match="Test warning message"):
            warn("Test warning message")


class TestClickHelpers:
    """Test click helper classes."""
    
    def test_ordered_group_init(self):
        """Test OrderedGroup initialization."""
        # Test default initialization
        group = OrderedGroup()
        assert group.commands == {}
        
        # Test with commands dict
        commands = {"cmd1": MagicMock(), "cmd2": MagicMock()}
        group = OrderedGroup(commands=commands)
        assert group.commands == commands
        
        # Test with name
        group = OrderedGroup(name="test_group")
        assert group.name == "test_group"
    
    def test_ordered_group_list_commands(self):
        """Test OrderedGroup list_commands method."""
        mock_cmd1 = MagicMock()
        mock_cmd2 = MagicMock()
        commands = {"cmd1": mock_cmd1, "cmd2": mock_cmd2}
        
        group = OrderedGroup(commands=commands)
        ctx = MagicMock()
        
        result = group.list_commands(ctx)
        assert result == commands


class TestLookupFunctions:
    """Test lookup functions for PyPI to conda name mapping."""
    
    @patch('conda_lock.lookup.cached_download_file')
    def test_get_pypi_lookup_http_url(self, mock_download):
        """Test _get_pypi_lookup with HTTP URL."""
        mock_mapping = {
            "test-package": {
                "conda_name": "test_package",
                "conda_forge": "test_package", 
                "pypi_name": "test-package"
            }
        }
        mock_download.return_value = json.dumps(mock_mapping).encode()
        
        # Clear the cache
        _get_pypi_lookup.cache_clear()
        
        result = _get_pypi_lookup("https://example.com/mapping.json")
        
        # Check that canonicalized names are used
        assert "test-package" in result
        assert result["test-package"]["conda_name"] == "test_package"
        assert result["test-package"]["pypi_name"] == "test-package"
        
        mock_download.assert_called_once_with(
            "https://example.com/mapping.json", 
            cache_subdir_name="pypi-mapping"
        )
    
    @patch('pathlib.Path.read_bytes')
    def test_get_pypi_lookup_file_url(self, mock_read_bytes):
        """Test _get_pypi_lookup with file:// URL."""
        mock_mapping = {
            "numpy": {
                "conda_name": "numpy",
                "conda_forge": "numpy",
                "pypi_name": "numpy"
            }
        }
        mock_read_bytes.return_value = json.dumps(mock_mapping).encode()
        
        # Clear the cache
        _get_pypi_lookup.cache_clear()
        
        result = _get_pypi_lookup("file:///path/to/mapping.json")
        
        assert "numpy" in result
        assert result["numpy"]["conda_name"] == "numpy"
    
    @patch('pathlib.Path.read_bytes')
    def test_get_pypi_lookup_yaml_file(self, mock_read_bytes):
        """Test _get_pypi_lookup with YAML file."""
        mock_mapping = {
            "requests": {
                "conda_name": "requests",
                "conda_forge": "requests",
                "pypi_name": "requests"
            }
        }
        
        try:
            import ruamel.yaml
            yaml = ruamel.yaml.YAML(typ="safe")
            from io import StringIO
            yaml_content = StringIO()
            yaml.dump(mock_mapping, yaml_content)
            yaml_bytes = yaml_content.getvalue().encode()
        except ImportError:
            # Fallback to basic YAML format if ruamel.yaml not available
            import yaml as pyyaml
            yaml_bytes = pyyaml.dump(mock_mapping).encode()
        
        mock_read_bytes.return_value = yaml_bytes
        
        # Clear the cache
        _get_pypi_lookup.cache_clear()
        
        result = _get_pypi_lookup("/path/to/mapping.yaml")
        
        assert "requests" in result
        assert result["requests"]["conda_name"] == "requests"
    
    @patch('conda_lock.lookup._get_pypi_lookup')
    def test_pypi_name_to_conda_name_found(self, mock_get_lookup):
        """Test pypi_name_to_conda_name when mapping exists."""
        mock_get_lookup.return_value = {
            "test-package": {
                "conda_name": "test_package_conda",
                "conda_forge": "test_package_forge",
                "pypi_name": "test-package"
            }
        }
        
        result = pypi_name_to_conda_name("test-package", "test_url")
        assert result == "test_package_conda"
    
    @patch('conda_lock.lookup._get_pypi_lookup')
    def test_pypi_name_to_conda_name_not_found(self, mock_get_lookup):
        """Test pypi_name_to_conda_name when mapping doesn't exist."""
        mock_get_lookup.return_value = {}
        
        result = pypi_name_to_conda_name("unknown-package", "test_url")
        assert result == "unknown-package"  # Should return the original name
    
    @patch('conda_lock.lookup._get_pypi_lookup')
    def test_conda_name_to_pypi_name(self, mock_get_pypi_lookup):
        """Test conda_name_to_pypi_name function."""
        mock_get_pypi_lookup.return_value = {
            "test-package": {
                "conda_name": "test_conda",
                "conda_forge": "test_forge",
                "pypi_name": "test-package"
            }
        }
        
        # Clear the cache
        _get_conda_lookup.cache_clear()
        
        result = conda_name_to_pypi_name("test_conda", "test_url")
        assert result == "test-package"
        
        # Test with unknown conda name
        result = conda_name_to_pypi_name("unknown_conda", "test_url")
        assert result == "unknown-conda"  # Should return canonicalized name


class TestVirtualPackageHelpers:
    """Test helper functions from virtual_package.py."""
    
    def test_virtual_package_basic(self):
        """Test basic VirtualPackage creation."""
        pkg = VirtualPackage(name="__test", version="1.0")
        assert pkg.name == "__test"
        assert pkg.version == "1.0"
        assert pkg.build_string == ""
    
    def test_virtual_package_with_build_string(self):
        """Test VirtualPackage with build string."""
        pkg = VirtualPackage(name="__cuda", version="11.2", build_string="h123456")
        assert pkg.name == "__cuda"
        assert pkg.version == "11.2"
        assert pkg.build_string == "h123456"
    
    def test_virtual_package_to_full_virtual_package(self):
        """Test VirtualPackage conversion to FullVirtualPackage."""
        pkg = VirtualPackage(name="__glibc", version="2.17", build_string="0")
        full_pkg = pkg.to_full_virtual_package()
        
        assert isinstance(full_pkg, FullVirtualPackage)
        assert full_pkg.name == "__glibc"
        assert full_pkg.version == "2.17"
        assert full_pkg.build_string == "0"
        assert full_pkg.build_number == 0
        assert full_pkg.package_type == "virtual_system"
    
    def test_full_virtual_package_build_property(self):
        """Test FullVirtualPackage build property."""
        # Test with build_string
        pkg = FullVirtualPackage(name="__test", version="1.0", build_string="abc123")
        assert pkg.build == "abc123"
        
        # Test without build_string (should use build_number)
        pkg = FullVirtualPackage(name="__test", version="1.0", build_number=42)
        assert pkg.build == "42"
    
    def test_virtual_package_to_repodata_entry(self):
        """Test VirtualPackage conversion to repodata entry."""
        pkg = VirtualPackage(name="__unix", version="0", build_string="0")
        fname, entry = pkg.to_repodata_entry(subdir="linux-64")
        
        assert fname == "__unix-0-0.tar.bz2"
        assert entry["name"] == "__unix"
        assert entry["version"] == "0"
        assert entry["build"] == "0"
        assert entry["subdir"] == "linux-64"
        assert entry["package_type"] == "virtual_system"
    
    def test_parse_virtual_package_spec_version_only(self):
        """Test _parse_virtual_package_spec with version only."""
        result = _parse_virtual_package_spec("__unix", "0")
        assert result.name == "__unix"
        assert result.version == "0"
        assert result.build_string == ""
    
    def test_parse_virtual_package_spec_with_build_string(self):
        """Test _parse_virtual_package_spec with version and build string."""
        result = _parse_virtual_package_spec("__archspec", "1 x86_64")
        assert result.name == "__archspec"
        assert result.version == "1"
        assert result.build_string == "x86_64"
    
    def test_parse_virtual_package_spec_complex_build_string(self):
        """Test _parse_virtual_package_spec with complex build string."""
        result = _parse_virtual_package_spec("__cuda", "11.2 h12345_0")
        assert result.name == "__cuda"
        assert result.version == "11.2"
        assert result.build_string == "h12345_0"


if __name__ == "__main__":
    pytest.main([__file__])