# Conda-lock Maintenance Tasks - January 2025

## Critical Maintenance Tasks (Priority 1)

### 1. Resolve TODO/FIXME Items in Core Code
**Status**: Active
**Impact**: High
**Effort**: Medium

**Issues identified:**
- `conda_lock/pypi_solver.py:307` - FIXME: how do deal with extras?
- `conda_lock/pypi_solver.py:397` - TODO: FIXME git ls-remote
- `conda_lock/pypi_solver.py:405` - TODO: need to handle git here
- `conda_lock/conda_solver.py:188` - TODO: Normalize URL here and inject env vars
- `conda_lock/conda_lock.py:1058` - TODO: Move to LockFile
- `conda_lock/models/lock_spec.py:69` - TODO: Should we store the auth info in here?
- `conda_lock/models/channel.py:11` - TODO: Detect environment variables that match a channel specified incorrectly
- `conda_lock/content_hash.py:176` - VPR unspecified rather than default (TODO: replace tests)

**Action**: Open individual PRs to address each TODO/FIXME item with proper implementation or documentation of why it can be deferred.

### 2. Update Pre-commit Hook Versions
**Status**: Active
**Impact**: Medium
**Effort**: Low

**Current versions in `.pre-commit-config.yaml`:**
- `pre-commit-hooks`: v5.0.0 (latest)
- `ruff-pre-commit`: v0.12.0 (check for updates)
- `mirrors-mypy`: v1.16.1 (check for updates)

**Action**: Update to latest versions and test compatibility.

### 3. CI/CD Workflow Maintenance
**Status**: Active
**Impact**: High
**Effort**: Medium

**Key issues:**
- GitHub Actions using pinned commits (good security practice)
- Test matrix spans Python 3.9-3.13 across multiple platforms
- Dependency lockfiles updated automatically via cron job

**Action**: 
- Review and update action versions quarterly
- Validate test matrix still covers supported Python versions
- Monitor the automated dependency update workflow

## Moderate Priority Tasks (Priority 2)

### 4. Vendored Package Updates
**Status**: Ongoing
**Impact**: Medium
**Effort**: High

**Current vendored packages:**
- Poetry 2.0.1
- Conda (multiple components)
- Cleo CLI framework
- Grayskull components

**Action**: 
- Establish quarterly review cycle for vendored package updates
- Document update procedures in CONTRIBUTING.md
- Create automated checks for outdated vendored packages

### 5. Test Infrastructure Improvements
**Status**: Good
**Impact**: Medium
**Effort**: Medium

**Current state:**
- Tests split into groups for parallel execution
- Good coverage across platforms
- Test duration tracking implemented

**Action**:
- Review test organization and reduce flaky tests
- Improve test performance where possible
- Document test running procedures

### 6. Documentation Updates
**Status**: Good
**Impact**: Low
**Effort**: Low

**Current state:**
- Comprehensive README
- Good API documentation
- Active documentation site

**Action**:
- Review documentation for accuracy with latest features
- Add troubleshooting guides for common issues
- Update installation instructions if needed

## Low Priority Tasks (Priority 3)

### 7. Code Quality Improvements
**Status**: Good
**Impact**: Low
**Effort**: Medium

**Current tools:**
- Ruff for linting and formatting
- MyPy for type checking
- Pre-commit hooks enforced

**Action**:
- Enable additional ruff rules gradually
- Improve type annotations coverage
- Consider adding more comprehensive static analysis

### 8. Dependency Security Monitoring
**Status**: Needs Setup
**Impact**: Medium
**Effort**: Low

**Action**:
- Set up automated dependency vulnerability scanning
- Add security policy documentation
- Establish process for handling security updates

## Recommended PRs to Open

### PR 1: Resolve Core TODO Items
**Files**: `conda_lock/pypi_solver.py`, `conda_lock/conda_solver.py`, `conda_lock/conda_lock.py`
**Description**: Address the most critical TODO/FIXME items in the core solver logic
**Priority**: High

### PR 2: Update Development Dependencies
**Files**: `.pre-commit-config.yaml`, `pixi.toml`
**Description**: Update pre-commit hooks and development dependencies to latest versions
**Priority**: Medium

### PR 3: CI/CD Maintenance
**Files**: `.github/workflows/*.yml`
**Description**: Update GitHub Actions to latest versions and review workflow efficiency
**Priority**: Medium

### PR 4: Test Organization Improvements
**Files**: `tests/`, `pyproject.toml`
**Description**: Improve test organization and reduce test execution time
**Priority**: Low

### PR 5: Documentation Updates
**Files**: `README.md`, `docs/`
**Description**: Update documentation for latest features and add troubleshooting guides
**Priority**: Low

## Monitoring and Maintenance Schedule

### Weekly
- Monitor CI/CD pipeline health
- Review open issues and PRs

### Monthly
- Update dependencies using existing automation
- Review test failures and flaky tests

### Quarterly
- Review and update vendored packages
- Update GitHub Actions versions
- Security audit of dependencies
- Review TODO/FIXME items for resolution

### Annually
- Major dependency updates
- Review and update Python version support matrix
- Documentation comprehensive review

## Notes

- Files under `conda_lock/_vendor/` are vendored and should not be modified directly
- The project uses pixi for package management - all commands should use `pixi run`
- Automated dependency updates are handled by `.github/workflows/update-lockfile.yaml`
- The project has good test coverage and CI/CD practices in place

## Contact and Escalation

For questions about these maintenance tasks, refer to:
- Project maintainers listed in CODEOWNERS
- GitHub issues for specific technical questions
- Documentation at https://conda.github.io/conda-lock/