"""Keep standalone Jireh application code independent of CROWN modules.

This is a static Python import guard, not a general dependency, supply-chain,
runtime import or data-isolation certification. It scans only src/jireh; the
archived CROWN parity reference under tests/ is intentionally outside scope.
"""

import ast
from pathlib import Path
import unittest


STANDALONE_ROOT = Path(__file__).resolve().parents[1] / "src" / "jireh"

# Top-level module names from CROWN code and adjacent tightly coupled apps.
# Django, Python standard-library and jireh.* imports are not prohibited.
FORBIDDEN_CROWN_ROOTS = frozenset(
    {
        "aid",
        "core",
        "crown_api",
        "financial_aid",
        "financial_aid_wizard",
        "households",
        "jireh_sgo",
        "ledger",
        "sandbox_demo",
    }
)


def forbidden_imports(source: str) -> list[tuple[int, str]]:
    """Return blocked *absolute* static imports; relative imports are local."""
    failures = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.partition(".")[0]
                if root in FORBIDDEN_CROWN_ROOTS:
                    failures.append((node.lineno, alias.name))
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            module = node.module or ""
            if module.partition(".")[0] in FORBIDDEN_CROWN_ROOTS:
                failures.append((node.lineno, module))
    return sorted(failures)


class StandaloneImportBoundaryTests(unittest.TestCase):
    def test_no_crown_application_imports(self):
        self.assertTrue(STANDALONE_ROOT.is_dir(), "Missing standalone source tree")
        violations = []
        for path in sorted(STANDALONE_ROOT.rglob("*.py")):
            relative = path.relative_to(STANDALONE_ROOT).as_posix()
            for line, module in forbidden_imports(path.read_text(encoding="utf-8")):
                violations.append(f"{relative}:{line} imports {module}")
        self.assertEqual(
            violations, [],
            "Standalone Jireh must not import CROWN services or models: "
            + "; ".join(violations),
        )

    def test_detects_direct_and_aliased_crown_imports(self):
        source = (
            "import core.models as model_alias\n"
            "from aid.services.award_engine import recommend_award\n"
            "from ledger import services\n"
            "import jireh.financial_aid.models\n"
        )
        self.assertEqual(
            forbidden_imports(source),
            [
                (1, "core.models"),
                (2, "aid.services.award_engine"),
                (3, "ledger"),
            ],
        )

    def test_allows_standalone_and_relative_imports(self):
        source = (
            "from .models import AidApplication\n"
            "from ..financial_aid import services\n"
            "from jireh.financial_aid.models import AidApplication\n"
            "from django.db import transaction\n"
            "import json\n"
        )
        self.assertEqual(forbidden_imports(source), [])

    def test_blocks_global_legacy_financial_aid_namespace(self):
        self.assertEqual(
            forbidden_imports(
                "from financial_aid.need_index import calculate_need_index\n"
                "import financial_aid_wizard.models\n"
            ),
            [(1, "financial_aid.need_index"), (2, "financial_aid_wizard.models")],
        )


if __name__ == "__main__":
    unittest.main()
