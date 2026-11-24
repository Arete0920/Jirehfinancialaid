# Standalone offline release packaging

Advances [#48](https://github.com/Arete0920/Jirehfinancialaid/issues/48), especially source provenance and repeatable dependency installation. This is **offline acceptance evidence**, not a deployed customer application, a production image, a hosting selection or authorization to release.

The source builder reads only the requested immutable Git commit. It checks every selected archived file against its tracked blob, refuses symlinks and missing required paths, and records the commit, tree, source archive SHA-256 and per-file digests. It does not include untracked files or working-tree edits. The selected source includes test/demo modules for acceptance and must not be treated as a hardened production distribution.

Run the builder in a Git checkout using Python 3.12:

```bash
python scripts/build_release_bundle.py --revision "$(git rev-parse HEAD)" --output artifacts/offline-bundle
```

The dedicated GitHub workflow downloads only the existing hash-pinned Linux CPython 3.12 binary wheels, installs them in a separate environment without an index, checks dependencies, and imports the packaged closed runtime with ephemeral fictional settings. It checks liveness and the closed route set without connecting to a database. The artifact contains the source tar, source evidence JSON, wheelhouse and SHA256SUMS. Verify checksums and trusted exact-commit CI before using it. Artifact retention is seven days; retain final evidence in an approved location.

This is a source/dependency installation rehearsal, not a platform-specific release build. It does not prove a production WSGI/ASGI server, TLS termination, least-privilege DB access, migration parity, encrypted persistent storage, customer routes, monitoring, backup, restore or rollback. It does not establish secret scanning or a signed build attestation. No host, cloud resource, real school, payment integration or production database is created or changed. Continue to use the canonical production-readiness ledger; D1–D3 and the other environment gates remain NOT TESTED until their independent evidence is available. Run the final exact-SHA build only when coordinated and authorized.
