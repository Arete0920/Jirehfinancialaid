# Local encrypted document backend — preproduction acceptance

**Issue:** #44. **Scope:** standalone Jireh only. **Status:** local/disposable validation implementation; not authorization to handle real family financial files or deploy.

## What is implemented

- `src/jireh/financial_aid/clamav_instream.py`: bounded ClamAV `zINSTREAM` protocol client. It accepts only a Unix domain socket or literal loopback IP; sends chunked scanner requests, waits for a conclusive `stream: OK` result, returns a detection as denied, and fails closed on timeouts, unavailable scanner and invalid/incomplete replies.
- `src/jireh/financial_aid/local_encrypted_backend.py`: authenticated AES-256-GCM local object storage with a fresh 96-bit nonce per object, object-key-scoped associated data, exclusive/private 0600 files inside a pre-existing 0700 process-owned directory, no symlink follow on the final path, bounded byte counts, atomic exclusive creation, authenticated readback, and idempotent deletion. Only canonical UUID object keys; no filenames, public URLs or API endpoints.
- Scanner is injected, must indicate a clean result, and is coupled to an independent conservative PDF signature check. A scanner's `FOUND` result or failure **never** permits a document to enter storage through the existing scoped document service.
- Tests exercise the ClamAV wire protocol, independent AES-GCM tamper/incorrect-key detection, wrong-object AAD, filesystem access restrictions and full Jireh authorized create/read/delete lifecycle with fictional bytes.

## Local setup / security boundaries

The storage directory must already be created by an operator using a nonprivileged process account; it must be owned by that account and have UNIX mode `0700`. Do not place it in a web-served directory or shared temp folder. Keep the 32-byte encryption key outside Git, outside logs, and outside the database. It must be delivered through a separately reviewed secrets mechanism. Losing it makes files unreadable; do not rotate it without an approved re-encryption and rollback procedure.

This implementation deliberately requires `JIREH_SYNTHETIC_DOCUMENTS_ONLY=True` through the existing test-only document service. The standalone runtime does not enable that setting. A preproduction ClamAV service must be local (Unix socket preferred); never expose the unencrypted ClamAV TCP protocol to a remote network. Configure scanner definition updates, secure daemon operation, scanning limits and operator alerts. An unavailable or outdated scanner is not an acceptable clean result.

The Python `cryptography` package is already **pinned for existing CI-only WebAuthn tests** through `requirements-webauthn-ci.txt`; this change does not extend the runtime dependency lock or declare any production-ready packaging. For any persistent hosted service, resolve and pin its platform-specific wheel hashes and deploy the key/scanner through approved infrastructure.

## Mandatory remaining work for #44

- Approve production topology (private cloud object store vs managed encrypted volume), budget, key management and recovery process; implement the corresponding provider and deployment wiring.
- Run a real ClamAV daemon with current definitions in a disposable environment; test clean samples, EICAR detection, timeout, outage, over-limit and error handling. Current CI stubs daemon replies and explicitly **does not** certify detection efficacy.
- Define permitted document categories, maximum sizes, data minimization, retention schedules, legal holds, erasure/backup treatment and incident procedures.
- Implement and certify safe bounded HTTP streaming upload/download for authorized family and officer roles with final CSRF, caching, authentication and tenant/household checks; add negative tests and deployed E2E.
- Add orphan file reconciliation if storage succeeded but DB persistence or cleanup failed, plus observable telemetry and operational recovery rehearsal.
- Test multi-process concurrency and actual deployed database/blob backups and restore. The test double and local backend are not an HA production service.

No real financial documents or payment mechanisms are activated by these changes. This is a useful functional local milestone for the document subsystem, **not closure of Issue #44**.
