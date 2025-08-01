# Transitive Dependency Dropping Bug in conda-lock

This repository contains a minimal reproducer for a bug in conda-lock where transitive dependencies are dropped from the lockfile, causing installation failures.

## **The Bug**

When using conda-lock with pip dependencies that have transitive dependencies, some of those transitive dependencies are not included in the final lockfile. This causes installation failures when trying to install the environment.

### **Example Scenario**

Given an environment with:
- `jupyter==1.1.1` (pip dependency)

Expected behavior:
- `jupyter` should be included
- `ipython` (transitive dependency of jupyter) should be included
- All other transitive dependencies should be included

Actual behavior:
- `jupyter` is included ✅
- `ipython` is **missing** ❌
- Installation fails due to missing dependencies

## **Files in this Repository**

- `USER_STORY.md` - Detailed user story describing the bug and its impact
- `minimal_reproducer.py` - Automated script to reproduce the bug
- `environment.yml` - Simple environment file for manual testing
- `ASSERTIONS_SUMMARY.md` - Mathematical analysis proving the bug exists

## **How to Reproduce**

### **Option 1: Automated Reproducer**

```bash
# Install conda-lock if you haven't already
pip install conda-lock

# Run the automated reproducer
python minimal_reproducer.py
```

### **Option 2: Manual Testing**

```bash
# Create the lockfile
conda-lock lock environment.yml

# Check if ipython is in the lockfile
grep -i ipython conda-lock.yml

# Try to install (this will likely fail)
conda-lock install conda-lock.yml
```

### **Option 3: Using the Test Case**

The bug is also demonstrated in the conda-lock test suite:

```bash
# Run the specific test that demonstrates the bug
pytest tests/test_conda_lock.py::test_solve_arch_transitive_deps -v
```

## **Expected Output**

When the bug is present, you should see:

1. **Lockfile generation succeeds** but is incomplete
2. **Missing transitive dependencies** like `ipython`
3. **Installation failures** due to missing packages
4. **Error messages** about packages not being available

## **Technical Details**

The bug manifests in the `apply_categories` function in `conda_lock/lockfile/__init__.py`:

```python
# In apply_categories function
for dep, roots in root_requests.items():
    targets = _seperator_munge_get(planned, dep)
    if len(targets) == 0:
        continue  # This skips category assignment for missing dependencies
```

When transitive dependencies like `ipython` are not found in the `planned` packages, the category assignment is skipped, and the dependency is effectively dropped from the lockfile.

## **Impact**

This bug has several negative impacts:

1. **Installation Failures**: Environments cannot be installed due to missing dependencies
2. **Reproducibility Issues**: Different users get different results
3. **Development Delays**: Time wasted debugging installation issues
4. **Trust Issues**: Users lose confidence in conda-lock

## **Workarounds**

Users have found several workarounds:

1. **Explicit Dependencies**: Manually add all transitive dependencies to the environment file
2. **Version Pinning**: Pin specific versions of transitive dependencies
3. **Alternative Tools**: Use conda/mamba directly instead of conda-lock

## **Expected Fix**

The fix should ensure that all transitive dependencies are properly included in the `planned` packages during the dependency resolution phase, before `apply_categories` is called.

## **Mathematical Proof**

Through rigorous assertion-based analysis, we have proven by contradiction that this bug exists in conda-lock. The `test_solve_arch_transitive_deps` test provides concrete evidence of the bug in action.

See `ASSERTIONS_SUMMARY.md` for the complete mathematical analysis.

## **Conclusion**

This bug undermines the core value proposition of conda-lock: creating reproducible environments. Users expect that when they specify a dependency like `jupyter`, all of its transitive dependencies will be automatically included in the lockfile. The current behavior breaks this expectation and creates unreliable environments.
