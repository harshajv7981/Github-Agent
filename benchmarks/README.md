# Patchwork benchmark harness

The harness evaluates fixed patch cases through the same sandbox used by the API.
Keep repository snapshots or stable public repositories in `cases.json`; do not use
live issues as a benchmark because their default branches change over time.

Example case:

```json
[
  {
    "name": "parser-regression",
    "repo_full_name": "owner/repository",
    "file_rewrites": {"tests/test_parser.py": "..."},
    "expected_status": "passed"
  }
]
```

Run it with:

```bash
PYTHONPATH=backend .venv/bin/python benchmarks/run.py benchmarks/cases.json
```