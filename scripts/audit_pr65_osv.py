"""Independent, read-only audit of PR #65's pinned npm lockfile.

Queries OSV for vulnerability IDs and inventories lockfile license strings.
This does NOT classify or waive SonarQube Advanced Security dependency risks,
which can include private license/malware policy findings unavailable to OSV.
No packages are installed or updated, no credentials required, no suppressions.
"""
import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

PR65_COMMIT = "dd980b5d3045db4b275a3acfec0fa5455a171f46"
LOCK_URL = (
    "https://raw.githubusercontent.com/Arete0920/Jirehfinancialaid/"
    + PR65_COMMIT + "/frontend/package-lock.json"
)
OSV_URL = "https://api.osv.dev/v1/querybatch"


def _download(url):
    with urlopen(Request(url, headers={"User-Agent": "jireh-pr65-audit/1.0"}), timeout=35) as response:
        data = response.read(5_000_001)
    if len(data) > 5_000_000:
        raise ValueError("Refusing oversized dependency response")
    return json.loads(data)


def _scan(lock):
    if lock.get("lockfileVersion") != 3 or type(lock.get("packages")) is not dict:
        raise ValueError("Unexpected npm lockfile structure")
    entries = []
    for path, value in lock["packages"].items():
        if "node_modules/" not in path:
            continue
        package = path.rsplit("node_modules/", 1)[-1]
        if type(value) is not dict or type(value.get("version")) is not str:
            raise ValueError("Missing installed package version")
        entries.append({
            "package": package,
            "version": value["version"],
            "license": value.get("license", "UNSPECIFIED"),
            "dev": bool(value.get("dev", False)),
            "optional": bool(value.get("optional", False)),
        })
    versions = sorted({(x["package"], x["version"]) for x in entries})
    if not versions:
        raise ValueError("No npm dependencies discovered")
    body = json.dumps({
        "queries": [
            {"package": {"ecosystem": "npm", "name": name}, "version": version}
            for name, version in versions
        ]
    }).encode("utf-8")
    request = Request(
        OSV_URL,
        body,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "jireh-pr65-audit/1.0",
        },
        method="POST",
    )
    with urlopen(request, timeout=60) as response:
        result = json.load(response)
    records = result.get("results")
    if type(records) is not list or len(records) != len(versions):
        raise ValueError("Incomplete OSV batch response")
    findings = []
    for (name, version), report in zip(versions, records):
        if type(report) is not dict:
            raise ValueError("Invalid OSV result")
        for vuln in report.get("vulns", []):
            if type(vuln) is not dict or type(vuln.get("id")) is not str:
                raise ValueError("Invalid OSV vulnerability")
            findings.append({
                "package": name, "version": version,
                "vulnerability_id": vuln["id"],
                "reference": "https://osv.dev/vulnerability/" + vuln["id"],
            })
    return entries, findings


def main():
    lock = _download(LOCK_URL)
    entries, findings = _scan(lock)
    licences = {}
    for p in entries:
        license_name = p["license"]
        if type(license_name) is not str:
            license_name = "UNSPECIFIED"
        licences.setdefault(license_name, []).append(
            {"package": p["package"], "version": p["version"], "dev": p["dev"]}
        )
    report = {
        "source_repo": "Arete0920/Jirehfinancialaid",
        "source_commit": PR65_COMMIT,
        "data_source": "OSV querybatch (public vulnerability database)",
        "scope": "Full installed npm lockfile, including dev and optional packages",
        "limitations": [
            "OSV vulnerability results are not SonarCloud proprietary SCA issues",
            "License labels come from the npm lockfile, not independent legal review",
            "An empty result cannot certify a dependency as safe or resolve a license risk",
        ],
        "installed_package_entries": len(entries),
        "findings": findings,
        "licenses": {k: sorted(v, key=lambda item: item["package"]) for k, v in sorted(licences.items())},
    }
    out = Path("artifacts/pr65-osv-independent-audit.json")
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("Source SHA:", PR65_COMMIT)
    print("Package entries:", len(entries))
    print("OSV vulnerability matches:", len(findings))
    for finding in findings:
        print("MATCH:", finding["package"], finding["version"], finding["vulnerability_id"])
    for label, packages in sorted(licences.items()):
        print("LICENSE:", label, "entries:", len(packages))
    print("Artifact:", out.as_posix())
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write("## Independent PR #65 dependency audit\n\n")
            handle.write(f"Pinned commit: \`{PR65_COMMIT}\`  \n")
            handle.write(f"npm entries: {len(entries)}  \nOSV matches: {len(findings)}  \n\n")
            handle.write("This does **not** resolve the two SonarCloud SCA findings.\n\n")
            for item in findings:
                handle.write(f"- {item['package']}@{item['version']}: {item['vulnerability_id']}\n")
    if findings:
        raise SystemExit("Independent OSV scan found vulnerabilities; investigate findings")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (HTTPError, URLError, ValueError, KeyError) as exc:
        raise SystemExit(
            "Independent audit could not finish: " + type(exc).__name__
        ) from None
