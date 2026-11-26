"""Enforce module boundaries introduced by the package refactor."""
import ast
from pathlib import Path

import pytest

from app.core.config import ROOT


def imports(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            yield node.module or ""
        elif isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)


@pytest.mark.parametrize("package", ["training", "questions"])
def test_domain_logic_does_not_depend_on_http_routes(package):
    for path in (ROOT / "app" / package).glob("*.py"):
        assert not any(name.startswith(("fastapi", "starlette", "app.api")) for name in imports(path)), path


@pytest.mark.parametrize("file,forbidden", [
    ("app/storage/history.py", "qdrant_client"),
    ("app/search/index.py", "sqlite3"),
])
def test_history_and_search_have_independent_storage_dependencies(file, forbidden):
    assert not any(name.startswith(forbidden) for name in imports(ROOT / file))


def test_project_root_does_not_change_with_package_depth():
    assert (ROOT / "Setup.cmd").is_file()
    assert (ROOT / "content/questions.json").is_file()
    assert (ROOT / "web/index.html").is_file()
