from __future__ import annotations

import ast
from pathlib import Path


P4_MODULES = (
    Path("adapters/gsd_execution_identity.py"),
    Path("adapters/gsd_execution_outcomes.py"),
    Path("adapters/gsd_execution_reconciliation.py"),
)
FORBIDDEN_IMPORTS = {"subprocess", "socket", "requests", "httpx", "boto3"}
FORBIDDEN_MODULE_WORDS = {"provider", "harness", "workspace"}


def test_p4_modules_have_no_real_dispatch_or_workspace_imports():
    for path in P4_MODULES:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module.split(".")[0])
        assert not FORBIDDEN_IMPORTS.intersection(imports), (path, imports)
        assert not any(word in import_name.lower() for import_name in imports for word in FORBIDDEN_MODULE_WORDS), (path, imports)


def test_p4_modules_do_not_claim_public_contract_or_release_authority():
    for path in P4_MODULES:
        source = path.read_text(encoding="utf-8").lower()
        assert "contracts/" not in source
        assert "release" not in source
        assert "promotion" not in source
