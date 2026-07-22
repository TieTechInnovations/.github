#!/usr/bin/env python3
"""Regenerate the "Recent activity" section of profile/README.md from org commit data.

Requires env vars:
  GH_TOKEN     - token with read access to the org's repos (private included)
  GH_ORG       - organization login, e.g. "TieTechInnovations"
"""
import os
import sys
import urllib.request
import json
from collections import Counter
from datetime import datetime, timedelta, timezone

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

API = "https://api.github.com"
GRAPH_DAYS = 56  # 8 weeks
TOP_REPOS = 5
TOP_LANGS = 5

PROFILE_DIR = os.path.join(os.path.dirname(__file__), "..", "profile")
README_PATH = os.path.join(PROFILE_DIR, "README.md")
ASSETS_DIR = os.path.join(PROFILE_DIR, "assets")
CHART_LIGHT_PATH = os.path.join(ASSETS_DIR, "commit-graph-light.png")
CHART_DARK_PATH = os.path.join(ASSETS_DIR, "commit-graph-dark.png")
START_MARK = "<!-- STATS:START -->"
END_MARK = "<!-- STATS:END -->"

# dataviz reference palette (references/palette.md): sequential blue, chart chrome & ink
CHART_THEME = {
    "light": {
        "bar": "#2a78d6",
        "surface": "#fcfcfb",
        "text_primary": "#0b0b0b",
        "text_muted": "#898781",
        "grid": "#e1e0d9",
        "baseline": "#c3c2b7",
    },
    "dark": {
        "bar": "#3987e5",
        "surface": "#1a1a19",
        "text_primary": "#ffffff",
        "text_muted": "#c3c2b7",
        "grid": "#2c2c2a",
        "baseline": "#383835",
    },
}


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
    since = datetime.now(timezone.utc) - timedelta(days=GRAPH_DAYS)
    since_iso = since.strftime("%Y-%m-%dT%H:%M:%SZ")
    since_date = since.date()

    repos = list_org_repos(org, token)
    repos = [r for r in repos if not r.get("archived")]

    commit_counts = Counter()
    author_counts = Counter()
    lang_counts = Counter()
    daily_counts = Counter()
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

            date_str = c.get("commit", {}).get("author", {}).get("date")
            if date_str:
                commit_date = datetime.strptime(date_str[:10], "%Y-%m-%d").date()
                daily_counts[commit_date] += 1

    days = [since_date + timedelta(days=i) for i in range(GRAPH_DAYS + 1)]
    series = [daily_counts.get(d, 0) for d in days]

    return {
        "since": since,
        "total_repos": len(repos),
        "active_repos": active_repos,
        "total_commits": total_commits,
        "top_repos": commit_counts.most_common(TOP_REPOS),
        "top_authors": author_counts.most_common(TOP_REPOS),
        "top_langs": lang_counts.most_common(TOP_LANGS),
        "days": days,
        "daily_series": series,
    }


def render_chart(days, series, path, theme):
    fig, ax = plt.subplots(figsize=(9, 2.6), dpi=200)
    fig.patch.set_facecolor(theme["surface"])
    ax.set_facecolor(theme["surface"])

    ax.bar(days, series, width=0.8, color=theme["bar"], linewidth=0, zorder=3)

    ax.set_ylim(bottom=0)
    ax.yaxis.grid(True, color=theme["grid"], linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)

    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.spines["bottom"].set_visible(True)
    ax.spines["bottom"].set_color(theme["baseline"])
    ax.spines["bottom"].set_linewidth(1)

    ax.tick_params(axis="both", length=0, labelsize=8, colors=theme["text_muted"])
    ax.set_yticks([t for t in ax.get_yticks() if t == int(t)])

    week_ticks = days[::7]
    ax.set_xticks(week_ticks)
    ax.set_xticklabels([d.strftime("%b %d") for d in week_ticks], color=theme["text_muted"])

    ax.set_title(
        f"Commits per day — last {GRAPH_DAYS} days",
        loc="left",
        fontsize=10,
        color=theme["text_primary"],
        pad=10,
    )

    fig.tight_layout()
    fig.savefig(path, facecolor=theme["surface"], bbox_inches="tight")
    plt.close(fig)


def render_section(stats):
    lines = []
    lines.append(
        f"In the last {GRAPH_DAYS} days: **{stats['total_commits']}** commits "
        f"across **{stats['active_repos']}/{stats['total_repos']}** active repos.\n"
    )

    lines.append(
        '<picture>\n'
        '  <source media="(prefers-color-scheme: dark)" srcset="assets/commit-graph-dark.png">\n'
        '  <img alt="Commits per day, last 8 weeks" src="assets/commit-graph-light.png">\n'
        '</picture>\n'
    )

    if stats["top_repos"]:
        lines.append("**Most active repos**")
        lines.append("")
        for name, count in stats["top_repos"]:
            lines.append(f"- `{name}` — {count} commit{'s' if count != 1 else ''}")
        lines.append("")

    if stats["top_authors"]:
        lines.append("**Top contributors**")
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

    os.makedirs(ASSETS_DIR, exist_ok=True)
    render_chart(stats["days"], stats["daily_series"], CHART_LIGHT_PATH, CHART_THEME["light"])
    render_chart(stats["days"], stats["daily_series"], CHART_DARK_PATH, CHART_THEME["dark"])

    section = render_section(stats)
    update_readme(section)
    print("README stats section and commit graph updated.")


if __name__ == "__main__":
    main()
