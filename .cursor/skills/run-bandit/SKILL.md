---
name: run-bandit
description: Run the Bandit security linter from the project's virtual environment on the midvatten repository. Use when the user asks to run bandit, perform a security scan, or check for security issues in Python code.
---

# Run Bandit Security Scan

## When to use

- User asks to run bandit or run a security scan
- User wants to check Python code for security issues
- User mentions bandit in the context of this repository

## How to run

From the **midvatten repository root** (project workspace root):

1. **Install bandit if needed** (e.g. if `bandit` is not installed in `.venv`):

   ```bash
   .venv/bin/python3 -m pip install bandit
   ```

2. **Run bandit**:

   ```bash
   .venv/bin/python3 -m bandit -r .
   ```

The `-r .` targets the current directory (repository root); Bandit recurses into subdirectories.

## Notes

- Use the project's `.venv`; do not assume a globally installed bandit.
- Run the command from the repository root so `-r .` covers the whole codebase.
