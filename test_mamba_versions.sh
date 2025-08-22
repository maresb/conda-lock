#!/bin/bash

# Script to test different mamba versions and reproduce the repodata_record.json issue

set -e

echo "Testing different mamba versions for repodata_record.json issue..."
echo "================================================================"

# Test versions that should work (before the regression)
WORKING_VERSIONS=("2.1.0" "2.0.0" "1.5.0")

# Test versions that have the issue (after the regression)
BROKEN_VERSIONS=("2.1.1" "2.2.0" "2.3.0" "2.3.1")

# Function to test a specific version
test_version() {
    local version=$1
    local expected_status=$2  # "working" or "broken"
    
    echo ""
    echo "Testing mamba version: $version (expected: $expected_status)"
    echo "--------------------------------------------------------"
    
    # Build the container
    echo "Building container with mamba version $version..."
    docker build --build-arg VERSION="$version" -t "bad-repodata-$version" -f Dockerfile.reproduce . 2>/dev/null
    
    if [ $? -ne 0 ]; then
        echo "❌ Failed to build container for version $version"
        return 1
    fi
    
    # Run the container and extract the repodata_record.json
    echo "Running container and extracting repodata_record.json..."
    docker run --rm "bad-repodata-$version" cat repodata_record.json > "repodata_record_${version}.json"
    
    if [ $? -ne 0 ]; then
        echo "❌ Failed to extract repodata_record.json for version $version"
        return 1
    fi
    
    # Analyze the extracted file
    echo "Analyzing repodata_record.json..."
    
    # Check for empty depends list
    local depends_count=$(jq '.depends | length' "repodata_record_${version}.json" 2>/dev/null || echo "0")
    local timestamp=$(jq '.timestamp' "repodata_record_${version}.json" 2>/dev/null || echo "null")
    local has_sha256=$(jq 'has("sha256")' "repodata_record_${version}.json" 2>/dev/null || echo "false")
    
    echo "  - depends count: $depends_count"
    echo "  - timestamp: $timestamp"
    echo "  - has sha256: $has_sha256"
    
    # Determine if this version has the issue
    local has_issue=false
    if [ "$depends_count" = "0" ] || [ "$timestamp" = "0" ] || [ "$has_sha256" = "false" ]; then
        has_issue=true
    fi
    
    # Report results
    if [ "$has_issue" = "true" ] && [ "$expected_status" = "working" ]; then
        echo "❌ UNEXPECTED: Version $version has the issue but should be working"
        return 1
    elif [ "$has_issue" = "false" ] && [ "$expected_status" = "broken" ]; then
        echo "❌ UNEXPECTED: Version $version is working but should have the issue"
        return 1
    elif [ "$has_issue" = "true" ] && [ "$expected_status" = "broken" ]; then
        echo "✅ EXPECTED: Version $version has the issue as expected"
    else
        echo "✅ EXPECTED: Version $version is working as expected"
    fi
    
    # Clean up
    docker rmi "bad-repodata-$version" >/dev/null 2>&1 || true
    rm -f "repodata_record_${version}.json"
    
    return 0
}

# Test working versions
echo ""
echo "Testing versions that should work correctly..."
for version in "${WORKING_VERSIONS[@]}"; do
    test_version "$version" "working"
done

# Test broken versions
echo ""
echo "Testing versions that should have the issue..."
for version in "${BROKEN_VERSIONS[@]}"; do
    test_version "$version" "broken"
done

echo ""
echo "Testing complete!"
echo "================================================================"
echo ""
echo "Summary:"
echo "- Versions 2.1.0 and earlier should work correctly"
echo "- Versions 2.1.1 and later should have the repodata_record.json issue"
echo ""
echo "The issue manifests as:"
echo "- Empty depends list (should contain actual dependencies)"
echo "- Zero timestamp (should be actual timestamp)"
echo "- Missing sha256 field"
echo "- Empty license field"