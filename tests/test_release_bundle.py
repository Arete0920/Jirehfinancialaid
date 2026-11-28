"""Offline exact-commit packaging tests using a disposable Git repository."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest


_SPEC = importlib.util.spec_from_file_location(
    "build_release_bundle", Path(__file__).resolve().parents[1] / "scripts/build_release_bundle.py",
)
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)


class ReleaseBundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.git("init", "-q")
        self.git("config", "user.name", "Fictional Test")
        self.git("config", "user.email", "fictional@example.invalid")
        fixture_paths = {*_MODULE.PATHS, "scripts/verify_restricted_runtime.py",
                         "docs/RELEASE_ACCEPTANCE_PROCEDURES.md"}
        for path in sorted(fixture_paths):
            name = path + "/__init__.py" if path == "src/jireh" else path
            file = self.repo / name
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text("fixture\n", encoding="utf-8")
        (self.repo / "excluded.txt").write_text("not selected", encoding="utf-8")
        self.commit()

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.repo), *args]).decode().strip()

    def commit(self):
        self.git("add", ".")
        self.git("commit", "-qm", "Fictional source")
        self.sha = self.git("rev-parse", "HEAD")

    def test_reproducible_exact_commit_and_manifest(self):
        (self.repo / "manage.py").write_text("dirty worktree", encoding="utf-8")
        (self.repo / ".env").write_text("untracked", encoding="utf-8")
        one, two = self.root / "one", self.root / "two"
        first = _MODULE.build_bundle(self.repo, self.sha, one)
        second = _MODULE.build_bundle(self.repo, self.sha, two)
        self.assertEqual(first, second)
        self.assertEqual((one / "jireh-source.tar").read_bytes(), (two / "jireh-source.tar").read_bytes())
        self.assertEqual(json.loads((one / "source-evidence.json").read_text()), first)
        self.assertFalse(first["authorizes_deployment"])
        self.assertEqual(first["files"]["manage.py"], hashlib.sha256(b"fixture\n").hexdigest())
        with tarfile.open(one / "jireh-source.tar") as tar:
            self.assertNotIn("jireh/.env", tar.getnames())
            self.assertNotIn("jireh/excluded.txt", tar.getnames())

    def test_demo_launchers_and_guides_are_included_in_verified_archive(self):
        output = self.root / "demo-bundle"
        evidence = _MODULE.build_bundle(self.repo, self.sha, output)
        required = {
            "scripts/run_local_browser_demo.py",
            "scripts/verify_local_browser_demo.py",
            "scripts/rehearse_synthetic_demo.py",
            "scripts/verify_restricted_runtime.py",
            "docs/RELEASE_ACCEPTANCE_PROCEDURES.md",
            "docs/LOCAL_BROWSER_DEMO.md",
            "docs/LOCAL_ENCRYPTED_DOCUMENT_BACKEND.md",
            "docs/SYNTHETIC_DEMO_REHEARSAL.md",
            "docs/RELEASE_PACKAGING.md",
            "docs/PRODUCTION_READINESS.md",
            "docs/REPOSITORY_PRESENTATION_AND_ATTRIBUTION_POLICY.md",
            "docs/questionnaire_v1_field_catalog.json",
        }
        with tarfile.open(output / "jireh-source.tar") as archive:
            for path in required:
                with self.subTest(path=path), archive.extractfile("jireh/" + path) as stream:
                    self.assertEqual(hashlib.file_digest(stream, "sha256").hexdigest(),
                                     evidence["files"][path])
            self.assertNotIn("jireh/excluded.txt", archive.getnames())

    def test_reject_missing_operational_acceptance_files(self):
        for index, path in enumerate(("scripts/verify_restricted_runtime.py",
                                      "docs/RELEASE_ACCEPTANCE_PROCEDURES.md")):
            with self.subTest(path=path):
                file = self.repo / path
                file.unlink()
                self.commit()
                with self.assertRaisesRegex(ValueError, "Required source paths missing"):
                    _MODULE.build_bundle(self.repo, self.sha, self.root / f"missing-{index}")
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_text("fixture\n", encoding="utf-8")
                self.commit()

    def test_reject_symbolic_revision_missing_path_and_overwrite(self):
        with self.assertRaises(ValueError):
            _MODULE.build_bundle(self.repo, "HEAD", self.root / "one")
        _MODULE.build_bundle(self.repo, self.sha, self.root / "two")
        with self.assertRaises(FileExistsError):
            _MODULE.build_bundle(self.repo, self.sha, self.root / "two")
        (self.repo / "manage.py").unlink()
        self.commit()
        with self.assertRaises(ValueError):
            _MODULE.build_bundle(self.repo, self.sha, self.root / "three")

    def test_reject_symlink_and_export_ignore(self):
        (self.repo / "src/jireh/alias").symlink_to("__init__.py")
        self.commit()
        with self.assertRaises(ValueError):
            _MODULE.build_bundle(self.repo, self.sha, self.root / "one")
        (self.repo / "src/jireh/alias").unlink()
        (self.repo / ".gitattributes").write_text("manage.py export-ignore\n", encoding="utf-8")
        self.commit()
        with self.assertRaises(ValueError):
            _MODULE.build_bundle(self.repo, self.sha, self.root / "two")


if __name__ == "__main__":
    unittest.main()
