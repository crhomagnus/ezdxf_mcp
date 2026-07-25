# Contributing

Contributions that improve correctness, tests, documentation, portability, or
security are welcome.

## Before opening a change

1. Confirm that the work is compatible with the project's noncommercial
   license.
2. Do not include proprietary code, production screenshots, credentials,
   account data, customer data, or private infrastructure details.
3. Add or update tests for behavioral changes.
4. Document security and compatibility implications.

## Local checks

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[all,dev]"
EZDXF_MCP_WORKSPACE="$PWD/dxf-workspace" .venv/bin/pytest -q
.venv/bin/ruff check src tests
.venv/bin/mypy src
.venv/bin/python -m build
```

## Contribution license

By intentionally submitting a contribution for inclusion in this project, you
represent that you have the right to submit it and agree that it may be
distributed under the PolyForm Noncommercial License 1.0.0 and any separate
commercial licenses offered by the project copyright holder.

If that dual-licensing permission is not acceptable, do not submit the
contribution.
