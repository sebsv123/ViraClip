#!/usr/bin/env python3
"""Create or update GitHub repo labels for ViraClip.

Usage:
    GITHUB_TOKEN=ghp_xxx python scripts/create_labels.py
    # or with explicit repo:
    GITHUB_TOKEN=ghp_xxx GITHUB_REPO=sebsv123/ViraClip python scripts/create_labels.py
"""
import os
import sys
import urllib.request
import json

REPO = os.environ.get("GITHUB_REPO", "sebsv123/ViraClip")
TOKEN = os.environ.get("GITHUB_TOKEN", "")

if not TOKEN:
    print("ERROR: GITHUB_TOKEN environment variable is required.")
    sys.exit(1)

LABELS = [
    {"name": "backend",        "color": "0075ca", "description": "Changes to backend Python code"},
    {"name": "frontend",       "color": "f9d0c4", "description": "Changes to Next.js frontend"},
    {"name": "docker",         "color": "e4e669", "description": "Docker / infrastructure changes"},
    {"name": "ci",             "color": "6e5494", "description": "CI/CD workflows"},
    {"name": "documentation",  "color": "0052cc", "description": "Documentation updates"},
    {"name": "dependencies",   "color": "cfd3d7", "description": "Dependency bumps"},
    {"name": "comfyui",        "color": "d93f0b", "description": "ComfyUI pipeline changes"},
    {"name": "scripts",        "color": "bfd4f2", "description": "Dev scripts and tooling"},
    {"name": "pipeline",       "color": "e11d48", "description": "Core video pipeline changes"},
    {"name": "audio",          "color": "fbca04", "description": "Audio processing changes"},
    {"name": "subtitles",      "color": "0e8a16", "description": "Caption / subtitle changes"},
    {"name": "b-roll",         "color": "b60205", "description": "B-roll selection and insertion"},
    {"name": "performance",    "color": "e4e669", "description": "Performance improvements"},
    {"name": "security",       "color": "ee0701", "description": "Security fixes"},
    {"name": "good first issue","color": "7057ff", "description": "Good for newcomers"},
    {"name": "bug",            "color": "d73a4a", "description": "Something is not working"},
    {"name": "enhancement",    "color": "a2eeef", "description": "New feature or request"},
    {"name": "wontfix",        "color": "ffffff", "description": "This will not be worked on"},
]


def api_request(method: str, path: str, data: dict | None = None):
    url = f"https://api.github.com/repos/{REPO}{path}"
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={
            "Authorization": f"token {TOKEN}",
            "Accept": "application/vnd.github.v3+json",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def main():
    print(f"Creating/updating labels for {REPO}...\n")
    ok = 0
    for label in LABELS:
        status, _ = api_request("POST", "/labels", label)
        if status == 201:
            print(f"  ✓ Created  : {label['name']}")
            ok += 1
        elif status == 422:  # already exists
            status2, _ = api_request("PATCH", f"/labels/{label['name'].replace(' ', '%20')}", label)
            if status2 == 200:
                print(f"  ↻ Updated  : {label['name']}")
                ok += 1
            else:
                print(f"  ✗ Failed   : {label['name']} (update returned {status2})")
        else:
            print(f"  ✗ Failed   : {label['name']} (POST returned {status})")

    print(f"\nDone: {ok}/{len(LABELS)} labels ready.")


if __name__ == "__main__":
    main()
