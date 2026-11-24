"""Offline regression tests for current dependency evidence."""
import importlib.util
from pathlib import Path
import unittest

_PATH = Path(__file__).resolve().parents[1] / "scripts/audit_current_dependencies.py"
_SPEC = importlib.util.spec_from_file_location("current_dependency_audit", _PATH)
audit = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(audit)


class CurrentDependencyAuditTests(unittest.TestCase):
    def test_current_inventory(self):
        pins = audit.collect_pins(audit.ROOT)
        self.assertEqual(set(pins), {
            "django", "asgiref", "sqlparse", "tzdata", "psycopg",
            "psycopg-binary", "typing-extensions", "fido2", "cryptography",
            "cffi", "pycparser", "playwright",
        })
        self.assertTrue(all(pin["hashes"] for name, pin in pins.items()
                            if name != "playwright"))

    def test_parse_extras_markers_and_continuations(self):
        h1, h2 = "a" * 64, "b" * 64
        content = (
            f"One[binary]==3.4 --hash=sha256:{h1} \\\n"
            f"    --hash=sha256:{h2}\n"
            f'tzdata==2026.6 ; sys_platform == "win32" --hash=sha256:{h1}\n'
        )
        self.assertEqual(audit.parse_manifest(content), {
            "one": ("3.4", [h1, h2]), "tzdata": ("2026.6", [h1]),
        })

    def test_invalid_requirements_fail_closed(self):
        h = "a" * 64
        for content in (
            "", "pkg>=1.0", "pkg==1.0", "-r other.txt",
            "pkg==1.0 --hash=sha256:abc",
            f"pkg==1.0 --hash=sha256:{h}\npkg==2.0 --hash=sha256:{h}",
        ):
            with self.subTest(content=content), self.assertRaises(ValueError):
                audit.parse_manifest(content)

    def test_osv_empty_and_explicit_findings(self):
        keys = [("pkg", "1.0")]
        self.assertEqual(audit.advisories(keys, {"results": [{}]}), [])
        self.assertEqual(audit.advisories(keys, {
            "results": [{"vulns": [{"id": "GHSA-abcd-1234-efgh"}]}],
        }), [{"name": "pkg", "version": "1.0", "id": "GHSA-abcd-1234-efgh"}])

    def test_incomplete_osv_response_is_not_clean(self):
        for response in (
            {}, {"results": []}, {"results": [None]},
            {"results": [{"next_page_token": "more"}]},
            {"results": [{"error": "unavailable"}]},
            {"results": [{"vulns": [None]}]},
            {"results": [{"vulns": [{"id": "not valid"}]}]},
        ):
            with self.subTest(response=response), self.assertRaises(ValueError):
                audit.advisories([("pkg", "1.0")], response)

    def test_published_hash_yank_and_latest_version(self):
        h1, h2, h3 = "a" * 64, "b" * 64, "c" * 64
        release = {
            "info": {"name": "Example_pkg", "version": "1.0"},
            "urls": [
                {"packagetype": "bdist_wheel", "digests": {"sha256": h1}, "yanked": False},
                {"packagetype": "bdist_wheel", "digests": {"sha256": h2}, "yanked": True},
            ],
        }
        current = {"info": {"name": "example-pkg", "version": "2.0"}}
        result = audit.release_evidence("example-pkg", "1.0", [h1, h2, h3], release, current)
        self.assertEqual(result["missing_pinned_hashes"], [h3])
        self.assertEqual(result["yanked_pinned_hashes"], [h2])
        self.assertFalse(result["matches_latest_pypi_version"])
        self.assertTrue(result["has_nonyanked_wheel"])
        with self.assertRaises(ValueError):
            audit.release_evidence("another", "1.0", [h1], release, current)
