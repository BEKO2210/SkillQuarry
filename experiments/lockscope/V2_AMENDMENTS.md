# LockScope v2 Amendments

## A1 — macOS PEP 668 isolation

First v2 workflow run: `31822890540`.

The macOS runner failed before syntax checking or any LockScope test because Homebrew Python 3.14 is marked as an externally managed environment (PEP 668), so the workflow's system-level `pip install` was rejected.

This is an infrastructure defect, not a semantic result.

Allowed correction:

- create a repository-local Python virtual environment on both semantic platforms and the real-repository job;
- install the exact same preregistered packages and versions into that venv;
- run the unchanged harness through the venv Python.

Unchanged:

- Rust/rust-analyzer versions;
- tree-sitter package versions;
- all 25 semantic cases;
- corrected compiler ground-truth expectations;
- repository commits;
- repair tasks;
- runtime thresholds;
- PASS/FAIL criteria.
