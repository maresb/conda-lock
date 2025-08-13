# User Story: Transitive Dependency Dropping Bug in conda-lock

## **The Problem**

As a data scientist working with Jupyter notebooks, I want to use conda-lock to create reproducible environments, but I encounter a bug where transitive dependencies are missing from the lockfile, causing installation failures.

## **The Scenario**

### **Initial Setup**

I'm working on a data analysis project and need to create a reproducible environment with Jupyter. I create an environment file:

```yaml
# environment.yml
name: data-analysis
channels:
  - conda-forge
dependencies:
  - python=3.10.9
  - pip=24.2
  - pip:
    - jupyter==1.1.1
```

### **Expected Behavior**

When I run `conda-lock lock`, I expect the lockfile to include:
- `python=3.10.9` (direct dependency)
- `pip=24.2` (direct dependency) 
- `jupyter==1.1.1` (direct pip dependency)
- `ipython` (transitive dependency of jupyter)
- All other transitive dependencies of jupyter

### **Actual Behavior**

The lockfile is generated successfully, but when I try to install it with `conda-lock install`, I get an error:

```
conda.exceptions.PackagesNotFoundError: The following packages are not available from current channels:
  - ipython
```

### **Root Cause Analysis**

The issue is that `ipython` (a transitive dependency of `jupyter`) is being dropped during the dependency resolution process. When conda-lock processes the environment:

1. ✅ `jupyter` is correctly identified as a pip dependency
2. ❌ `ipython` (transitive dependency of `jupyter`) is **not included** in the `planned` packages
3. ❌ When `apply_categories` runs, it can't assign categories to `ipython` because it doesn't exist in `planned`
4. ❌ The final lockfile is missing `ipython`, causing installation to fail

### **Impact**

This bug has several negative impacts:

1. **Installation Failures**: The environment cannot be installed because missing transitive dependencies
2. **Reproducibility Issues**: Different users get different results depending on their local environment
3. **Development Delays**: Time is wasted debugging why environments don't install correctly
4. **Trust Issues**: Users lose confidence in conda-lock's ability to create reliable environments

### **Workarounds**

Users have found several workarounds:

1. **Explicit Dependencies**: Manually add all transitive dependencies to the environment file
2. **Version Pinning**: Pin specific versions of transitive dependencies
3. **Alternative Tools**: Use conda/mamba directly instead of conda-lock

### **Reproduction Steps**

1. Create `environment.yml` with the content above
2. Run `conda-lock lock`
3. Run `conda-lock install`
4. Observe that `ipython` is missing and installation fails

### **Technical Details**

The bug manifests in the `apply_categories` function in `conda_lock/lockfile/__init__.py`:

```python
# In apply_categories function
for dep, roots in root_requests.items():
    targets = _seperator_munge_get(planned, dep)
    if len(targets) == 0:
        continue  # This skips category assignment for missing dependencies
```

When `ipython` is not found in `planned` packages, the category assignment is skipped, and the dependency is effectively dropped from the lockfile.

### **Expected Fix**

The fix should ensure that all transitive dependencies are properly included in the `planned` packages during the dependency resolution phase, before `apply_categories` is called.

## **Conclusion**

This bug undermines the core value proposition of conda-lock: creating reproducible environments. Users expect that when they specify a dependency like `jupyter`, all of its transitive dependencies will be automatically included in the lockfile. The current behavior breaks this expectation and creates unreliable environments.