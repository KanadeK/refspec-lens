# Contributing

Use Python 3.11+ and Git 2.43+ for the integration fixtures.

```sh
python -m venv .venv
# Activate your environment, then:
python -m pip install -e . build ruff
python -m unittest discover -s tests -v
python -m ruff check .
python -m build
python examples/demo.py
```

Keep real Git regression fixtures for behavior changes. Describe the failing
workflow and limitations in an issue before broadening scope. Do not submit real
private repository data. Runtime dependencies are intentionally empty. No workflow
commits code or updates dependencies automatically.
