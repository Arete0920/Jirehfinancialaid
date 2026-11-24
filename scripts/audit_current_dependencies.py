"""Exact-checkout public dependency evidence; not release certification.

Audit the locked runtime and cryptography packages and pinned browser test
tool. No upgrades, installation, credentials or suppression. Public OSV and
PyPI results cannot replace private security, malware or license analysis.
"""
import json
import re
import subprocess
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
MANIFESTS = ("requirements.txt", "requirements-webauthn-ci.txt")
BROWSER = ".github/workflows/browser-demo.yml"
PIN = re.compile(
    r"(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[A-Za-z0-9_,.-]+\])?"
    r"==(?P<version>[0-9]+(?:\.[0-9]+)+)"
    r'(?:\s*;\s*sys_platform\s*==\s*"win32")?'
    r"(?P<hashes>(?:\s+--hash=sha256:[0-9a-f]{64})+)"
)


def normalize(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def parse_manifest(content):
    pins = {}
    for line in content.replace("\\\n", " ").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = PIN.fullmatch(line)
        if match is None:
            raise ValueError("Unsupported or unpinned requirement")
        name = normalize(match["name"])
        if name in pins:
            raise ValueError("Duplicate requirement")
        pins[name] = (match["version"], sorted(set(
            re.findall(r"sha256:([0-9a-f]{64})", match["hashes"])
        )))
    if not pins:
        raise ValueError("Empty manifest")
    return pins


def collect_pins(root):
    result = {}
    for manifest in MANIFESTS:
        for name, (version, hashes) in parse_manifest(
            (root / manifest).read_text(encoding="utf-8")
        ).items():
            if name in result:
                raise ValueError("Duplicate cross-manifest requirement")
            result[name] = {"version": version, "hashes": hashes, "source": manifest}
    browser = re.findall(
        r'(?m)^\s*python -m pip install --only-binary=:all: "playwright==([0-9]+(?:\.[0-9]+)+)"\s*$',
        (root / BROWSER).read_text(encoding="utf-8"),
    )
    if len(browser) != 1 or "playwright" in result:
        raise ValueError("Missing or ambiguous browser test-tool pin")
    result["playwright"] = {"version": browser[0], "hashes": [], "source": BROWSER}
    return result


def request_json(url, body=None):
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = Request(
        url, data=data,
        headers={"User-Agent": "jireh-dependency-evidence/1.0",
                 "Accept": "application/json", "Content-Type": "application/json"},
        method="GET" if data is None else "POST",
    )
    limit = 12_000_000
    with urlopen(request, timeout=30) as response:
        payload = response.read(limit + 1)
    if len(payload) > limit:
        raise ValueError("Oversized dependency evidence")
    result = json.loads(payload)
    if type(result) is not dict:
        raise ValueError("Invalid evidence response")
    return result


def advisories(keys, response):
    records = response.get("results")
    if type(records) is not list or len(records) != len(keys):
        raise ValueError("Incomplete OSV response")
    findings = []
    for (name, version), record in zip(keys, records):
        if (type(record) is not dict or record.get("next_page_token")
                or set(record) - {"vulns", "next_page_token"}):
            raise ValueError("Incomplete or unexpected OSV package evidence")
        vulns = record.get("vulns", [])
        if type(vulns) is not list:
            raise ValueError("Malformed advisory list")
        for vuln in vulns:
            if (type(vuln) is not dict or type(vuln.get("id")) is not str
                    or not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", vuln["id"])):
                raise ValueError("Malformed advisory identifier")
            findings.append({"name": name, "version": version, "id": vuln["id"]})
    return findings


def release_evidence(name, version, hashes, release, current):
    info, latest, urls = release.get("info"), current.get("info"), release.get("urls")
    if (type(info) is not dict or type(latest) is not dict or type(urls) is not list
            or normalize(info.get("name", "")) != name
            or normalize(latest.get("name", "")) != name
            or info.get("version") != version
            or not isinstance(latest.get("version"), str) or not latest["version"]):
        raise ValueError("PyPI identity/version mismatch")
    wheels = {}
    for item in urls:
        if type(item) is not dict or item.get("packagetype") != "bdist_wheel":
            continue
        digest = item.get("digests", {}).get("sha256")
        if type(digest) is str and re.fullmatch(r"[0-9a-f]{64}", digest):
            wheels[digest] = item.get("yanked") is False
    if not wheels:
        raise ValueError("No published wheel evidence")
    return {
        "latest_pypi_version": latest["version"],
        "matches_latest_pypi_version": version == latest["version"],
        "missing_pinned_hashes": sorted(set(hashes) - set(wheels)),
        "yanked_pinned_hashes": sorted(h for h in hashes if h in wheels and not wheels[h]),
        "has_nonyanked_wheel": any(wheels.values()),
        "manifest_hash_count": len(hashes),
    }


def main():
    pins = collect_pins(ROOT)
    keys = sorted((name, pin["version"]) for name, pin in pins.items())
    sha = subprocess.check_output(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True,
    ).strip()
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("Invalid checkout SHA")
    findings = advisories(keys, request_json("https://api.osv.dev/v1/querybatch", {
        "queries": [{"package": {"ecosystem": "PyPI", "name": name}, "version": version}
                    for name, version in keys],
    }))
    packages = []
    for name, version in keys:
        pin = pins[name]
        url = "https://pypi.org/pypi/" + quote(name, safe="")
        evidence = release_evidence(
            name, version, pin["hashes"],
            request_json(url + "/" + quote(version, safe="") + "/json"),
            request_json(url + "/json"),
        )
        packages.append({"name": name, "version": version, "source": pin["source"], **evidence})
    report = {
        "source_sha": sha, "package_count": len(packages), "packages": packages,
        "public_osv_findings": findings,
        "limitations": [
            "Public OSV and PyPI evidence only; not full security, malware, license or secret scanning.",
            "Latest published version is not necessarily compatible or approved.",
            "Browser tool is version-pinned, not hash-locked; transitive browser tooling is outside this inventory.",
            "Operating-system, native library, container and workflow-action evidence is separate.",
        ],
    }
    out = ROOT / "artifacts/current-dependency-evidence.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("Checkout:", sha)
    print("Package pins:", len(packages))
    print("Public OSV matches:", len(findings))
    for item in packages:
        print(item["name"], item["version"], "latest published:", item["latest_pypi_version"],
              "missing hashes:", len(item["missing_pinned_hashes"]),
              "yanked hashes:", len(item["yanked_pinned_hashes"]))
    for finding in findings:
        print("ADVISORY:", finding["name"], finding["version"], finding["id"])
    return int(bool(findings or any(
        p["missing_pinned_hashes"] or p["yanked_pinned_hashes"]
        or not p["has_nonyanked_wheel"] for p in packages
    )))


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (HTTPError, URLError, ValueError, OSError, KeyError, TypeError, AttributeError) as exc:
        raise SystemExit("Current dependency evidence incomplete: " + type(exc).__name__) from None
