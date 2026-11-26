#!/usr/bin/env python3
"""Enforce Jireh's prospective repository presentation policy, not Git history."""

from __future__ import annotations

import argparse
import codecs
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
# These exact control files necessarily describe prohibited vocabulary or test it.
# Changes to them still require owner review; this is not a general directory exemption.
CONTROL_EXCEPTIONS = {
    'docs/REPOSITORY_PRESENTATION_AND_ATTRIBUTION_POLICY.md',
    'scripts/ci/repository_presentation_gate.py',
    'tests/test_repository_presentation_gate.py',
}
# Text-based media (such as SVG) also require visual/content review.
ASSET_SUFFIXES = {
    '.svg', '.png', '.jpg', '.jpeg', '.gif', '.webp', '.ico', '.bmp',
    '.tif', '.tiff', '.avif', '.heic', '.pdf', '.eps', '.ps',
    '.doc', '.docx', '.ppt', '.pptx', '.xls', '.xlsx', '.odt', '.odp',
    '.mp3', '.wav', '.ogg', '.mp4', '.mov', '.webm',
    '.woff', '.woff2', '.ttf', '.otf', '.zip', '.tar', '.gz',
}
# Each record must contain a factual reason and an actual owner-decision reference.
# Exact text exceptions: (location, line, matched term, SHA-256 of the full line).
# Line 0 denotes a filename. No blanket dependency, vendor, or metadata exclusions.
REVIEWED_REFERENCES: dict[tuple[str, int, str, str], tuple[str, str]] = {}
# Exact tracked object: (path, Git object SHA).
REVIEWED_ASSETS: dict[tuple[str, str], tuple[str, str]] = {}
# Exact uploaded release asset: (release ID, asset ID, SHA-256 digest).
REVIEWED_RELEASE_ASSETS: dict[tuple[int, int, str], tuple[str, str]] = {}
FIRST_PARTY_ASSOCIATIONS = {'OWNER', 'MEMBER', 'COLLABORATOR'}

BRANDING = re.compile(
    r'(?<![A-Za-z0-9])(?:'
    r'open[\s_-]?ai|chat[\s_-]?gpt|codex|copilot|anthropic|claude|gemini|'
    r'deepseek|perplexity|gpt(?:[-_ ]?\d[\w.-]*)?|llms?|'
    r'ai|artificial[\s_-]+intelligence|generative[\s_-]+ai|'
    r'autonomous[\s_-]+engineer|'
    r'(?:entirely|wholly|fully|100\s*%)\s+human[-\s]+(?:written|authored|developed|built)'
    r')(?![A-Za-z0-9])',
    re.IGNORECASE,
)


def matches(text: str) -> list[tuple[int, str]]:
    """Return line numbers and matched terms; no sensitive file contents printed."""
    return [
        (line_number, match.group())
        for line_number, line in enumerate(text.splitlines(), 1)
        for match in BRANDING.finditer(line)
    ]


def _reviewed(record: tuple[str, str] | None) -> bool:
    # CI validates the record's shape; the owner validates the referenced decision.
    return bool(record and len(record) == 2 and
                all(isinstance(value, str) and value.strip() for value in record))


def _reference_violations(location: str, text: str, *, filename: bool = False) -> list[str]:
    lines = [(0, text)] if filename else enumerate(text.splitlines(), 1)
    violations = []
    for number, line in lines:
        for match in BRANDING.finditer(line):
            term = match.group()
            key = (location, number, term.casefold(), hashlib.sha256(line.encode()).hexdigest())
            if not _reviewed(REVIEWED_REFERENCES.get(key)):
                label = f'{location}: filename' if filename else f'{location}:{number}'
                violations.append(f'{label}: unreviewed policy reference ({term})')
    return violations


def _decode_text(raw: bytes) -> str | None:
    # Inspect text independent of extension, including BOM-marked Unicode.
    if raw.startswith((codecs.BOM_UTF32_LE, codecs.BOM_UTF32_BE)):
        encoding = 'utf-32'
    elif raw.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        encoding = 'utf-16'
    else:
        encoding = 'utf-8-sig'
    try:
        text = raw.decode(encoding)
    except UnicodeError:
        return None
    if any(ord(char) < 32 and char not in '\t\r\n\f' for char in text):
        return None
    return text


def tracked_violations(root: Path) -> tuple[list[str], int]:
    # Read the actual tracked Git objects, not mutable working-tree paths or symlink targets.
    listing = subprocess.check_output(['git', '-C', str(root), 'ls-files', '--stage', '-z'])
    entries = [entry for entry in listing.split(b'\0') if entry]
    if not entries:
        return ['No tracked files: cannot establish coverage'], 0
    violations: list[str] = []
    asset_count = 0
    for entry in entries:
        header, raw_path = entry.split(b'\t', 1)
        mode, oid, stage = header.decode('ascii').split()
        rel = raw_path.decode('utf-8')
        if stage != '0':
            violations.append(f'{rel}: unresolved Git index entry')
            continue
        violations.extend(_reference_violations(rel, rel, filename=True))
        text = None
        if mode != '160000':  # A gitlink names a commit, not a blob.
            raw = subprocess.check_output(['git', '-C', str(root), 'cat-file', 'blob', oid])
            text = _decode_text(raw)
        requires_review = (
            text is None or mode not in {'100644', '100755'} or
            Path(rel).suffix.lower() in ASSET_SUFFIXES
        )
        if requires_review:
            asset_count += 1
            if not _reviewed(REVIEWED_ASSETS.get((rel, oid))):
                violations.append(f'{rel}: media, nontext or link object requires recorded review ({oid})')
        if text is not None and rel not in CONTROL_EXCEPTIONS:
            violations.extend(_reference_violations(rel, text))
    return violations, asset_count


def _event_object(environ: dict[str, str], key: str) -> dict:
    event_path = environ.get('GITHUB_EVENT_PATH')
    if not event_path:
        raise ValueError('Missing event payload')
    event = json.loads(Path(event_path).read_text(encoding='utf-8'))
    if not isinstance(event, dict) or not isinstance(event.get(key), dict):
        raise ValueError('Invalid event object')
    return event[key]


def _positive_id(value: object) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError('Invalid event identifier')
    return value


def _optional_text(value: object) -> str:
    if value is None:
        return ''
    if not isinstance(value, str):
        raise ValueError('Invalid text field')
    return value


def _required_text(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError('Missing or invalid text field')
    return value


def _narrative_violations(environ: dict[str, str], event_name: str,
                          key: str, label: str) -> list[str]:
    if environ.get('GITHUB_EVENT_NAME') != event_name:
        return []
    try:
        item = _event_object(environ, key)
        number = _positive_id(item['number'])
        if key == 'issue':
            association = _required_text(item['author_association'])
            if association not in FIRST_PARTY_ASSOCIATIONS:
                return []  # External reports are not adopted first-party guidance.
        title = _required_text(item['title'])
        body = _optional_text(item.get('body'))
    except (OSError, UnicodeError, ValueError, KeyError, TypeError) as exc:
        return [f'Cannot verify {label} title/body ({type(exc).__name__})']
    return (
        _reference_violations(f'{label} #{number} title', title) +
        _reference_violations(f'{label} #{number} body', body)
    )


def pr_violations(environ: dict[str, str]) -> list[str]:
    return _narrative_violations(environ, 'pull_request', 'pull_request', 'PR')


def issue_violations(environ: dict[str, str]) -> list[str]:
    return _narrative_violations(environ, 'issues', 'issue', 'Issue')


def release_violations(environ: dict[str, str]) -> list[str]:
    if environ.get('GITHUB_EVENT_NAME') != 'release':
        return []
    try:
        item = _event_object(environ, 'release')
        release_id = _positive_id(item['id'])
        fields = {
            'name': _optional_text(item.get('name')),
            'body': _optional_text(item.get('body')),
            'tag': _required_text(item['tag_name']),
        }
        assets = item['assets']
        if not isinstance(assets, list):
            raise ValueError('Invalid asset list')
        violations = []
        for field, value in fields.items():
            violations.extend(_reference_violations(f'Release {release_id} {field}', value))
        for asset in assets:
            if not isinstance(asset, dict):
                raise ValueError('Invalid release asset')
            asset_id = _positive_id(asset['id'])
            name = _required_text(asset['name'])
            digest = _optional_text(asset.get('digest'))
            location = f'Release {release_id} asset {asset_id}'
            violations.extend(_reference_violations(location, name))
            if (not re.fullmatch(r'sha256:[0-9a-f]{64}', digest) or
                    not _reviewed(REVIEWED_RELEASE_ASSETS.get((release_id, asset_id, digest)))):
                violations.append(f'{location}: uploaded asset requires recorded exact-digest review')
        return violations
    except (OSError, UnicodeError, ValueError, KeyError, TypeError) as exc:
        return [f'Cannot verify release narrative/assets ({type(exc).__name__})']


def metadata_violations(metadata: dict) -> list[str]:
    try:
        fields = {
            'name': _required_text(metadata['name']),
            'description': _optional_text(metadata['description']),
            'homepage': _optional_text(metadata['homepage']),
        }
        topics = metadata['topics']
        if not isinstance(topics, list):
            raise ValueError('Invalid repository topics')
        fields.update({f'topic {index}': _required_text(topic)
                       for index, topic in enumerate(topics, 1)})
        return [
            finding
            for field, value in fields.items()
            for finding in _reference_violations(f'Repository {field}', value)
        ]
    except (ValueError, KeyError, TypeError) as exc:
        return [f'Cannot verify repository metadata ({type(exc).__name__})']


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--metadata-file', type=Path)
    args = parser.parse_args()
    try:
        violations, asset_count = tracked_violations(ROOT)
    except (OSError, UnicodeError, ValueError, subprocess.CalledProcessError) as exc:
        print(f'Repository presentation gate: unable to inspect Git index ({type(exc).__name__})')
        return 1
    violations.extend(pr_violations(os.environ))
    violations.extend(issue_violations(os.environ))
    violations.extend(release_violations(os.environ))
    if args.metadata_file is not None:
        try:
            metadata = json.loads(args.metadata_file.read_text(encoding='utf-8'))
            violations.extend(metadata_violations(metadata))
        except (OSError, UnicodeError, ValueError, TypeError) as exc:
            violations.append(f'Cannot read repository metadata ({type(exc).__name__})')
    print(f'Repository presentation gate: {asset_count} media, nontext or link objects subject to recorded review')
    if violations:
        for violation in violations:
            print(violation)
        return 1
    print('Repository presentation gate: PASS (tracked objects, applicable event narrative'
          + (', repository metadata' if args.metadata_file is not None else '')
          + '; manual review obligations remain)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
