"""The reach half must not depend on the serve half.

This package does two jobs. It **reaches** sources that speak different
substrates — the trust profiles verify an ANS SCITT receipt, a DNSSEC chain, a
signed agent card — and it **serves** records as a NANDA-compatible registry.

Only the first is something the corroboration stack needs. The second is a
registry: a thing that stack audits. Every fault fixed in 0.7.0 was in the serve
half, and the trust profiles are the best-tested code here, which is not a
coincidence — `ProofResult` is substrate-neutral by design and `SmAgentFacts` is
one substrate's schema.

Keeping the dependency one-way is what makes it possible to separate them later
without a rewrite. This test pins it so the seam cannot rot in the meantime.
"""

from __future__ import annotations

import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent / "sm_bridge"

SERVE = {
    "router",
    "gateway",
    "converter",
    "store",
    "federation",
    "feed",
    "cli",
    "binding_write",
    "tlog",
}


def _runtime_imports(path: pathlib.Path) -> set[str]:
    """Modules imported when this file actually runs.

    Imports guarded by `if TYPE_CHECKING:` are excluded: they cost nothing at
    runtime and are broken by a forward reference, not by a refactor.
    """
    tree = ast.parse(path.read_text())
    type_only: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.If):
            test = node.test
            name = getattr(test, "id", None) or getattr(test, "attr", None)
            if name == "TYPE_CHECKING":
                for child in ast.walk(node):
                    type_only.add(id(child))
    found: set[str] = set()
    for node in ast.walk(tree):
        if id(node) in type_only:
            continue
        if isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module.replace("sm_bridge.", "").split(".")[0])
        elif isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name.replace("sm_bridge.", "").split(".")[0])
    return found


def test_trust_profiles_do_not_import_the_serving_half() -> None:
    offenders: dict[str, set[str]] = {}
    for path in sorted((ROOT / "trust").rglob("*.py")):
        leaked = _runtime_imports(path) & SERVE
        if leaked:
            offenders[path.name] = leaked
    assert offenders == {}, (
        f"trust/ must not depend on the serving half at runtime, but {offenders}. "
        "The reach half is what the corroboration stack consumes; the serve half "
        "is a registry that stack audits. Keeping the arrow one-way is what makes "
        "separating them a move rather than a rewrite."
    )


def test_the_serving_half_is_the_side_that_depends() -> None:
    # The control. If nothing in the serving half imports trust/, the assertion
    # above is vacuous and would keep passing after a split went wrong.
    dependents = {
        path.stem
        for path in sorted(ROOT.glob("*.py"))
        if path.stem in SERVE and "trust" in _runtime_imports(path)
    }
    assert dependents, "expected the serving half to import trust/; the boundary test is vacuous without it"
