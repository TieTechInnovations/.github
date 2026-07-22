#!/usr/bin/env python3
"""Regenerate the "Recent activity" section of profile/README.md from org commit data.

Requires env vars:
  GH_TOKEN     - token with read access to the org's repos (private included)
  GH_ORG       - organization login, e.g. "TieTechInnovations"
"""
import os
import sys
import time
import urllib.request
import json
from collections import Counter
from datetime import datetime, timedelta, timezone

API = "https://api.github.com"
LOOKBACK_DAYS = 7
TOP_REPOS = 5
TOP_LANGS = 5

README_PATH = os.path.join(os.path.dirname(__file__), "..", "profile", "README.md")
START_MARK = "<!-- STATS:START -->"
END_MARK = "<!-- STATS:END -->"


def gh_request(path, token, params=None):
    url = f"{API}{path}"
    if params:
        query = "&".join(f"{k}={v}" for k, v in params.items())
        url = f"{url}?{query}"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "tapp-engine-org-readme-bot",
        },
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode()), resp.headers


def gh_paginated(path, token, params=None, max_pages=10):
    params = dict(params or {})
    params.setdefault("per_page", 100)
    page = 1
    items = []
    while page <= max_pages:
        params["page"] = page
        data, _ = gh_request(path, token, params)
        if not data:
            break
        items.extend(data)
        if len(data) < int(params["per_page"]):
            break
        page += 1
    return items


def list_org_repos(org, token):
    return gh_paginated(f"/orgs/{org}/repos", token, {"type": "all"})


def list_recent_commits(org, repo, token, since_iso):
    try:
        return gh_paginated(
            f"/repos/{org}/{repo}/commits", token, {"since": since_iso}, max_pages=5
        )
    except urllib.error.HTTPError as e:
        # Empty repos / no commit access on this branch -> skip quietly
        if e.code in (404, 409):
            return []
        raise


def build_stats(org, token):
    since = datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)
    since_iso = since.strftime("%Y-%m-%dT%H:%M:%SZ")

    repos = list_org_repos(org, token)
    repos = [r for r in repos if not r.get("archived")]

    commit_counts = Counter()
    author_counts = Counter()
    lang_counts = Counter()
    total_commits = 0
    active_repos = 0

    for repo in repos:
        name = repo["name"]
        if repo.get("language"):
            lang_counts[repo["language"]] += 1

        commits = list_recent_commits(org, name, token, since_iso)
        if not commits:
            continue

        active_repos += 1
        commit_counts[name] = len(commits)
        total_commits += len(commits)

        for c in commits:
            author = (c.get("author") or {}).get("login") or (
                c.get("commit", {}).get("author", {}).get("name")
            )
            if author:
                author_counts[author] += 1

    return {
        "since": since,
        "total_repos": len(repos),
        "active_repos": active_repos,
        "total_commits": total_commits,
        "top_repos": commit_counts.most_common(TOP_REPOS),
        "top_authors": author_counts.most_common(TOP_REPOS),
        "top_langs": lang_counts.most_common(TOP_LANGS),
    }


def render_section(stats):
    lines = []
    lines.append(
        f"In the last {LOOKBACK_DAYS} days: **{stats['total_commits']}** commits "
        f"across **{stats['active_repos']}/{stats['total_repos']}** active repos.\n"
    )

    if stats["top_repos"]:
        lines.append("**Most active repos**")
        lines.append("")
        for name, count in stats["top_repos"]:
            lines.append(f"- `{name}` — {count} commit{'s' if count != 1 else ''}")
        lines.append("")

    if stats["top_authors"]:
        lines.append("**Top contributors this week**")
        lines.append("")
        for author, count in stats["top_authors"]:
            lines.append(f"- {author} — {count} commit{'s' if count != 1 else ''}")
        lines.append("")

    if stats["top_langs"]:
        top = ", ".join(f"`{lang}`" for lang, _ in stats["top_langs"])
        lines.append(f"**Primary languages**: {top}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def update_readme(section_body):
    with open(README_PATH, "r", encoding="utf-8") as f:
        content = f.read()

    if START_MARK not in content or END_MARK not in content:
        print(f"Markers {START_MARK!r}/{END_MARK!r} not found in {README_PATH}", file=sys.stderr)
        sys.exit(1)

    before = content.split(START_MARK)[0]
    after = content.split(END_MARK)[1]

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    footer_marker = "<sub>Last updated:"
    if footer_marker in after:
        after = after.split(footer_marker)[0] + f"<sub>Last updated: {timestamp}</sub>\n</div>\n"

    new_content = f"{before}{START_MARK}\n{section_body}{END_MARK}{after}"

    with open(README_PATH, "w", encoding="utf-8") as f:
        f.write(new_content)


def main():
    token = os.environ.get("GH_TOKEN")
    org = os.environ.get("GH_ORG")
    if not token or not org:
        print("GH_TOKEN and GH_ORG environment variables are required", file=sys.stderr)
        sys.exit(1)

    stats = build_stats(org, token)
    section = render_section(stats)
    update_readme(section)
    print("README stats section updated.")


if __name__ == "__main__":
    main()
