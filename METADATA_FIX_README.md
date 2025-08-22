# Mamba Repodata Record Issue Fix

## Problem Description

This document describes a robust fix for a critical issue in conda-lock where mamba (versions 2.1.1+) writes incomplete metadata to `repodata_record.json` files when installing from explicit lockfiles.

### The Issue

When installing packages from explicit lockfiles using mamba/micromamba versions 2.1.1 and later, the `repodata_record.json` files are written with incomplete metadata:

```json
{
    "depends": [],           // ❌ Should contain actual dependencies
    "timestamp": 0,          // ❌ Should be actual timestamp
    "sha256": null,          // ❌ Should be present
    "license": ""            // ❌ Should contain license info
}
```

This causes conda-lock to fail because it relies on the `depends` field to build the dependency graph.

### Root Cause

The issue occurs because mamba reads metadata from the package URL during installation but doesn't recognize that this metadata is incomplete. It writes the incomplete metadata to `repodata_record.json` instead of extracting complete metadata from the downloaded package archive.

### Affected Versions

- **Working**: mamba/micromamba versions 2.1.0 and earlier
- **Broken**: mamba/micromamba versions 2.1.1 and later

## Solution Overview

The fix implements a robust, multi-layered approach to metadata retrieval:

1. **Primary**: Read from `repodata_record.json`
2. **Validation**: Check metadata completeness
3. **Fallback 1**: Extract from package archive (`.conda` or `.tar.bz2`)
4. **Fallback 2**: Fetch from package URL (last resort)
5. **Error Handling**: Clear error messages with actionable suggestions

## Implementation Details

### New Module: `metadata_validator.py`

The core of the fix is a new module that provides:

- **Metadata validation**: Detects incomplete metadata fields
- **Package extraction**: Reads metadata from package archives
- **URL fallback**: Fetches basic metadata from package URLs
- **Robust retrieval**: Combines multiple methods for best results

### Key Functions

#### `validate_metadata(metadata)`
Validates metadata completeness and returns issues found:
- Empty `depends` list
- Zero `timestamp`
- Missing `sha256`
- Empty `license` field
- Missing required fields

#### `extract_metadata_from_conda_package(package_path)`
Extracts metadata from package files:
- Reads `info/repodata_record.json` from package
- Falls back to `info/index.json` if needed
- Converts between metadata formats

#### `get_robust_metadata(pkgs_dir, dist_name, fallback_url)`
Main function that orchestrates metadata retrieval:
1. Tries `repodata_record.json`
2. Validates metadata
3. Falls back to package extraction
4. Falls back to URL fetching
5. Provides clear error messages

### Updated Functions

#### `_get_repodata_record()`
Enhanced to use robust metadata handling:
- Accepts fallback URL parameter
- Uses new validation and fallback logic
- Provides better error reporting

#### `_reconstruct_fetch_actions()`
Updated to pass fallback URLs from link actions.

## Usage

### Automatic Handling

The fix is transparent to users - conda-lock automatically:
- Detects incomplete metadata
- Attempts to recover complete information
- Provides clear error messages if recovery fails

### Manual Validation

You can manually validate metadata:

```python
from conda_lock.metadata_validator import validate_metadata

with open("repodata_record.json") as f:
    metadata = json.load(f)

is_valid, issues = validate_metadata(metadata)
if not is_valid:
    print("Metadata issues found:", issues)
```

## Testing

### Test Scripts

1. **`test_repodata_issue.py`**: Python script to reproduce and test the issue
2. **`Dockerfile.reproduce`**: Docker container to reproduce the issue
3. **`test_mamba_versions.sh`**: Script to test different mamba versions

### Running Tests

```bash
# Test the fix
python test_repodata_issue.py

# Test different mamba versions
chmod +x test_mamba_versions.sh
./test_mamba_versions.sh

# Build reproduction container
docker build -f Dockerfile.reproduce -t bad-repodata .
```

### Unit Tests

Comprehensive test suite in `tests/test_metadata_validator.py`:
- Metadata validation
- Package extraction
- Fallback mechanisms
- Error handling
- Integration scenarios

## Error Messages

### Incomplete Metadata Error

```
IncompleteMetadataError: Unable to obtain complete metadata for ipykernel-6.30.1-pyh82676e8_0. 
The repodata_record.json file appears to be incomplete due to a known mamba issue 
when installing from explicit lockfiles.

Issues found:
- empty_depends: depends list is empty (should contain actual dependencies)
- zero_timestamp: timestamp is 0 (should be actual timestamp)
- missing_sha256: sha256 field is missing
- empty_license: license field is empty
```

### Suggestions

The system provides actionable suggestions:

```
Suggestions for ipykernel-6.30.1-pyh82676e8_0:
- The package dependencies are missing. This is a critical issue for conda-lock. 
  Consider reinstalling the package or using a different mamba version.
- The package timestamp is invalid. This may cause issues with dependency resolution.
- The package SHA256 hash is missing. This may affect package verification.
```

## Configuration

### Environment Variables

- `CONDA_LOCK_METADATA_STRICT`: Enable strict metadata validation (default: True)
- `CONDA_LOCK_METADATA_FALLBACK`: Enable fallback mechanisms (default: True)

### Logging

The module provides detailed logging:
- `DEBUG`: Fallback attempts and metadata extraction details
- `WARNING`: Incomplete metadata issues
- `INFO`: Successful metadata recovery

## Performance Impact

- **Minimal overhead**: Validation only occurs when metadata is read
- **Efficient fallbacks**: Package extraction is fast for local files
- **URL fallback**: Only used as last resort with timeout protection

## Compatibility

- **Backward compatible**: Works with existing conda-lock installations
- **Mamba versions**: Supports all mamba/micromamba versions
- **Package formats**: Works with both `.conda` and `.tar.bz2` packages
- **Platforms**: Cross-platform compatible

## Future Improvements

### Potential Enhancements

1. **Caching**: Cache extracted metadata to avoid repeated extraction
2. **Parallel extraction**: Extract metadata from multiple packages simultaneously
3. **Remote validation**: Validate metadata against remote repositories
4. **Auto-repair**: Automatically fix common metadata issues

### Integration Opportunities

1. **conda-forge**: Integrate with conda-forge metadata validation
2. **mamba**: Contribute fix upstream to mamba
3. **conda**: Ensure compatibility with conda's metadata handling

## Troubleshooting

### Common Issues

1. **Package not found**: Check package cache directories
2. **Permission errors**: Ensure read access to package files
3. **Network issues**: URL fallback may fail in restricted environments

### Debug Mode

Enable debug logging to see detailed fallback attempts:

```python
import logging
logging.getLogger('conda_lock.metadata_validator').setLevel(logging.DEBUG)
```

## Contributing

### Reporting Issues

When reporting metadata issues:
1. Include mamba/micromamba version
2. Provide `repodata_record.json` contents
3. Include installation method (lockfile vs. spec)
4. Attach relevant error messages

### Development

To contribute to the fix:
1. Run the test suite: `pytest tests/test_metadata_validator.py`
2. Test with real packages
3. Ensure backward compatibility
4. Update documentation

## Conclusion

This fix provides a robust, production-ready solution to the mamba metadata issue. It ensures conda-lock continues to work reliably with all mamba versions while providing clear feedback when issues occur.

The multi-layered approach maximizes the chances of successful metadata retrieval while maintaining performance and user experience.