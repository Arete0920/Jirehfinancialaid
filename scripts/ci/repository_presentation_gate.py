#!/usr/bin/env python3
"""Enforce Jireh's prospective repository presentation policy, not Git history."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
TEXT_EXTENSIONS = {
    '.md', '.txt', '.rst', '.py', '.js', '.jsx', '.mjs', '.cjs', '.ts', '.tsx',
    '.json', '.yml', '.yaml', '.toml', '.ini', '.cfg', '.sh', '.ps1', '.html',
    '.css', '.svg', '.xml',
}
# These files necessarily describe the prohibited vocabulary or test the control.
CONTROL_EXCEPTIONS = {
    'docs/REPOSITORY_PRESENTATION_AND_ATTRIBUTION_POLICY.md',
    'scripts/ci/repository_presentation_gate.py',
    'tests/test_repository_presentation_gate.py',
}
# Upstream dependency metadata is not first-party product or authoring language.
LOCKFILE_NAMES = {'package-lock.json', 'npm-shrinkwrap.json', 'yarn.lock', 'pnpm-lock.yaml'}
THIRD_PARTY_PREFIXES = ('vendor/', 'node_modules/', 'third_party/')
BRANDING = re.compile(
    r'(?<![A-Za-z0-9])(?:'
    r'open[\s_-]?ai|chat[\s_-]?gpt|codex|copilot|anthropic|claude|gemini|'
    r'deepseek|perplexity|gpt(?:[-_ ]?\d[\w.-]*)?|llms?|'
    r'ai|artificial[\s_-]+intelligence|generative[\s_-]+ai'
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


def tracked_violations(root: Path) -> tuple[list[str], int]:
    filenames = subprocess.check_output(['git', '-C', str(root), 'ls-files', '-z'])
    paths = [p for p in filenames.decode('utf-8').split('\0') if p]
    if not paths:
        return ['No tracked files: cannot establish coverage'], 0
    violations: list[str] = []
    skipped_binary = 0
    for rel in paths:
        if rel in CONTROL_EXCEPTIONS or rel.startswith(THIRD_PARTY_PREFIXES):
            continue
        if Path(rel).name in LOCKFILE_NAMES:
            continue
        for _, term in matches(rel):
            violations.append(f'{rel}: prohibited branding in filename ({term})')
        path = root / rel
        if path.suffix.lower() not in TEXT_EXTENSIONS:
            skipped_binary += 1
            continue
        try:
            content = path.read_text(encoding='utf-8-sig')
        except (UnicodeError, OSError) as exc:
            violations.append(f'{rel}: cannot inspect tracked text ({type(exc).__name__})')
            continue
        for line_number, term in matches(content):
            violations.append(f'{rel}:{line_number}: prohibited branding ({term})')
    return violations, skipped_binary


def pr_violations(environ: dict[str, str]) -> list[str]:
    if environ.get('GITHUB_EVENT_NAME') != 'pull_request':
        return []
    event_path = environ.get('GITHUB_EVENT_PATH')
    if not event_path:
        return ['Missing pull request event payload; cannot verify PR title/body']
    try:
        event = json.loads(Path(event_path).read_text(encoding='utf-8'))
        pr = event['pull_request']
        title, body = pr['title'], pr.get('body') or ''
        if not isinstance(title, str) or not isinstance(body, str):
            raise ValueError('Invalid pull request title/body')
    except (OSError, UnicodeError, ValueError, KeyError, TypeError) as exc:
        return [f'Cannot verify PR title/body ({type(exc).__name__})']
    return [
        f'PR {field}:{line_number}: prohibited branding ({term})'
        for field, value in [('title', title), ('body', body)]
        for line_number, term in matches(value)
    ]


def main() -> int:
    try:
        violations, skipped_binary = tracked_violations(ROOT)
    except (OSError, UnicodeError, subprocess.CalledProcessError) as exc:
        print(f'Repository presentation gate: unable to inspect Git tree ({exc})')
        return 1
    violations.extend(pr_violations(os.environ))
    print(f'Repository presentation gate: {skipped_binary} nontext files require separate review')
    if violations:
        for violation in violations:
            print(violation)
        return 1
    print('Repository presentation gate: PASS (tracked first-party text + PR narrative only)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
