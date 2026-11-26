# Standalone offline release packaging

Advances [#48](https://github.com/Arete0920/Jirehfinancialaid/issues/48), especially source provenance and repeatable dependency installation. This is **offline acceptance evidence**, not a deployed customer application, a production image, a hosting selection or authorization to release.

The source builder reads only the requested immutable Git commit. It checks every selected archived file against its tracked blob, refuses symlinks and missing required paths, and records the commit, tree, source archive SHA-256 and per-file digests. It does not include untracked files or working-tree edits. The selected source includes test/demo modules for acceptance and must not be treated as a hardened production distribution.

Run the builder in a Git checkout using Python 3.12:

```bash
python scripts/build_release_bundle.py --revision "$(git rev-parse HEAD)" --output artifacts/offline-bundle
```

The dedicated GitHub workflow downloads only the existing hash-pinned Linux CPython 3.12 binary wheels, installs them in a separate environment without an index, checks dependencies, and imports the packaged closed runtime with ephemeral fictional settings. It checks liveness and the closed route set without connecting to a production database. It also starts the packaged demo using the offline-installed dependencies, checks the loopback presenter page and workspace sign-in, and stops the temporary process. The artifact contains the source tar, source evidence JSON, wheelhouse and SHA256SUMS. The source now includes the local demo launcher, browser verifier, onboarding rehearsal and the relevant guides. Verify checksums and trusted exact-commit CI before using it. Artifact retention is seven days; retain final evidence in an approved location.

## Use the packaged guided demonstration

On a trusted Linux or WSL2 workstation with Python 3.12, unpack the verified
artifact, verify `SHA256SUMS` from the artifact directory, and install the
packaged application and preproduction dependencies without an index:

```sh
sha256sum -c SHA256SUMS
tar -xf jireh-source.tar
python3.12 -m venv .venv
.venv/bin/python -m pip install --no-index --find-links wheels --only-binary=:all: --require-hashes -r jireh/requirements.txt -r jireh/requirements-webauthn-ci.txt
.venv/bin/python -m pip check
.venv/bin/python jireh/scripts/run_local_browser_demo.py
```

Follow the included `jireh/docs/LOCAL_BROWSER_DEMO.md` on the same machine
at `http://127.0.0.1:8765/local-demo/`. The presenter uses only the seeded
fictional personas. Never expose the loopback service, enter real records, or
reuse a pre-existing database. Ctrl+C stops the temporary demonstration.

The ordinary Chromium workflow now builds the archive from the actual checked
out Git commit and runs the existing browser suite from extracted source,
rather than introducing a second full browser run. Its evidence includes the
source manifest identifying the tested commit and tree. A PR checkout may be
a GitHub-generated merge commit; final release evidence must identify the
exact protected-main commit. Playwright and Chromium are separately installed
test tools, not included in the offline application wheelhouse. The Linux
wheelhouse is not a native Windows installer. A presenter using a preinstalled
browser does not need Playwright to run the demo.

The bundle, Chromium and dependency workflows remain path-filtered and are
manually dispatchable. A protected-main push that changes the canonical
`docs/PRODUCTION_READINESS.md` checkpoint runs all three automatically.
The Chromium workflow also watches `manage.py` and the questionnaire field
catalog, which affect extracted-source browser acceptance. This does not
change required branch protection or authorize deployment. The bundle startup
rehearsal is not a replacement for the Chromium suite. For the final
candidate, obtain the offline-bundle, packaged Chromium and dependency
evidence for the same protected-main SHA, inspect the actual presentation,
and record the owner's acceptance separately.

This is a source/dependency installation rehearsal, not a platform-specific release build. It does not prove a production WSGI/ASGI server, TLS termination, least-privilege DB access, migration parity, encrypted persistent storage, customer routes, monitoring, backup, restore or rollback. It does not establish secret scanning or a signed build attestation. No host, cloud resource, real school, payment integration or production database is created or changed. Continue to use the canonical production-readiness ledger; D1–D3 and the other environment gates remain NOT TESTED until their independent evidence is available. Run the final exact-SHA build only when coordinated and authorized.
