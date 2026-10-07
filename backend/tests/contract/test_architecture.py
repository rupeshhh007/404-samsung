"""T-ARC-01: dependency direction for the canonical domain boundary."""

import ast
from pathlib import Path


_BACKEND = Path(__file__).resolve().parents[2] / "interlock"


def _imports(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            yield node.module


def test_t_arc_01_domain_never_imports_adapter_layer():
    for path in (_BACKEND / "domain").glob("*.py"):
        assert not any(name.startswith("interlock.adapters") for name in _imports(path)), path


def test_t_arc_01_samsung_adapter_does_not_import_domain():
    samsung = _BACKEND / "adapters" / "samsung.py"
    assert not any(name.startswith("interlock.domain") for name in _imports(samsung))
