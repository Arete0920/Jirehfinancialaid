"""Build an exact-commit source bundle for offline acceptance, not deployment."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import tarfile
import tempfile


PATHS = (
    "README.md", "manage.py", "requirements.txt", "requirements-webauthn-ci.txt",
    "src/jireh", "docs/questionnaire_v1_field_catalog.json",
    "scripts/run_local_browser_demo.py", "scripts/verify_local_browser_demo.py",
    "scripts/verify_authenticated_customer_portal.py",
    "scripts/rehearse_synthetic_demo.py",
    "docs/LOCAL_BROWSER_DEMO.md", "docs/LOCAL_ENCRYPTED_DOCUMENT_BACKEND.md",
    "docs/SYNTHETIC_DEMO_REHEARSAL.md", "docs/RELEASE_PACKAGING.md",
    "docs/PRODUCTION_READINESS.md", "docs/REPOSITORY_PRESENTATION_AND_ATTRIBUTION_POLICY.md",
)


def _git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args])


def _digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def build_bundle(repo, revision, output):
    if re.fullmatch(r"[0-9a-f]{40}", revision) is None:
        raise ValueError("Exact full commit SHA required")
    repo, output = Path(repo).resolve(), Path(output).resolve()
    if _git(repo, "rev-parse", "--verify", revision + "^{commit}").decode().strip() != revision:
        raise ValueError("Revision must identify a commit")
    tree = _git(repo, "rev-parse", revision + "^{tree}").decode().strip()
    entries = _git(repo, "ls-tree", "-r", "-z", revision, "--", *PATHS)
    expected = set()
    for entry in entries.split(b"\0"):
        if not entry:
            continue
        info, name = entry.split(b"\t", 1)
        mode, kind, _ = info.split()
        path = PurePosixPath(name.decode("utf-8"))
        if (kind != b"blob" or mode not in (b"100644", b"100755")
                or path.is_absolute() or ".." in path.parts):
            raise ValueError("Unsafe tracked source entry")
        expected.add(str(path))
    if not all(path in expected or any(p.startswith(path + "/") for p in expected) for path in PATHS):
        raise ValueError("Required source paths missing")
    output.mkdir(parents=True, exist_ok=True)
    archive, manifest = output / "jireh-source.tar", output / "source-evidence.json"
    if archive.exists() or manifest.exists():
        raise FileExistsError("Refusing to overwrite existing evidence")
    with tempfile.TemporaryDirectory(dir=output) as staging:
        staged = Path(staging) / archive.name
        with staged.open("wb") as stream:
            subprocess.run(["git", "-C", str(repo), "archive", "--format=tar", "--prefix=jireh/",
                            revision, "--", *PATHS], stdout=stream, check=True)
        records = {}
        with tarfile.open(staged, "r:") as tar:
            for member in tar:
                path = PurePosixPath(member.name)
                if path.is_absolute() or ".." in path.parts or not path.parts or path.parts[0] != "jireh":
                    raise ValueError("Unsafe archive path")
                if member.isdir():
                    continue
                relative = str(PurePosixPath(*path.parts[1:]))
                if not member.isfile() or relative not in expected or relative in records:
                    raise ValueError("Unexpected archive member")
                with tar.extractfile(member) as stream:
                    digest = hashlib.file_digest(stream, "sha256").hexdigest()
                # Verify archive bytes against the commit, including export transformations.
                blob = _git(repo, "cat-file", "blob", revision + ":" + relative)
                if digest != hashlib.sha256(blob).hexdigest():
                    raise ValueError("Archived content differs from tracked blob")
                records[relative] = digest
        if set(records) != expected:
            raise ValueError("Archive does not contain the complete selected source")
        evidence = {"schema": 1, "purpose": "offline-source-acceptance", "commit": revision,
                    "tree": tree, "archive_sha256": _digest(staged), "files": records,
                    "authorizes_deployment": False}
        staged_manifest = Path(staging) / manifest.name
        staged_manifest.write_text(json.dumps(evidence, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        # Exclusive creation prevents concurrent runs from replacing evidence.
        with archive.open("xb") as destination, staged.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                destination.write(chunk)
        with manifest.open("xb") as destination:
            destination.write(staged_manifest.read_bytes())
    return evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".")
    parser.add_argument("--revision", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = build_bundle(args.repo, args.revision, args.output)
    print(f"Verified source bundle: {result['commit']} ({len(result['files'])} tracked files)")


if __name__ == "__main__":
    main()
