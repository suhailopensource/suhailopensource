#!/usr/bin/env python3
"""
Regenerates every auto-updated block in README.md straight from the GitHub API.

Blocks it owns (everything between the markers is machine-written):
  stats     -> the headline badge strip
  oss       -> full table of merged PRs to repos I don't own (with star counts)
  issues    -> bugs/reports I filed upstream
  activity  -> latest public GitHub events

Everything outside those markers is hand-written and never touched.
Stdlib only -- no pip install needed in CI.
"""

import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict

USER = "suhailopensource"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
README = os.path.join(ROOT, "README.md")

API = "https://api.github.com"
TOKEN = os.environ.get("GITHUB_TOKEN", "")

# Issues only count when they land in a repo I actually work on. That keeps
# ancient "please deploy this" noise out of the table without a manual list.
EXTRA_ISSUE_REPOS = {"nocodb/nocodb", "sequelize/sequelize"}
ISSUES_SINCE = "2026-01-01"
# The upstream-bugs table is for defects, not questions or meta threads.
NOT_A_BUG = re.compile(r"^\s*(question|questions|q:|help|vouch|is this)\b", re.I)
MIN_STARS = 500

# One-line "what I touched there", keyed by repo. Unknown repos fall back to
# the repo's own description, so a brand-new project still renders sensibly.
FOCUS = {
    "TryGhost/Ghost": "Admin editor validation",
    "directus/directus": "Items API · translations relation",
    "eclipse-theia/theia": "Toolbar enablement · preview CSS",
    "getsentry/sentry-javascript": "Tracing core · idle spans",
    "GoogleChrome/web-vitals": "INP + CLS attribution",
    "up-for-grabs/up-for-grabs.net": "Project index",
    "VoidenHQ/voiden": "File explorer · CLI runner",
    "etro-js/etro": "Canvas render loop · perf",
    "get-convex/convex-backend": "Function spec · validators",
    "get-convex/better-auth": "Convex adapter semantics",
}

# A few upstream titles are meaningless out of context. Keyed by "repo#number".
TITLE_OVERRIDES = {
    "up-for-grabs/up-for-grabs.net#5992":
        "List prefID on up-for-grabs.net with curated good-first-issues",
}

BADGE = ("https://img.shields.io/badge/{label}-{value}-{color}"
         "?style=for-the-badge&labelColor=0D1117&logo={logo}&logoColor=white")


# --------------------------------------------------------------------------- api

def get(url, params=None):
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": f"{USER}-readme-updater",
    }
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    req = urllib.request.Request(url, headers=headers)
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as err:
            # Search API is aggressively rate limited; back off and retry.
            if err.code in (403, 429) and attempt < 3:
                time.sleep(8 * (attempt + 1))
                continue
            raise


def search(query, cap=100):
    items, page = [], 1
    while len(items) < cap:
        data = get(f"{API}/search/issues", {
            "q": query, "per_page": 100, "page": page,
            "sort": "created", "order": "desc",
        })
        batch = data.get("items", [])
        items.extend(batch)
        if len(batch) < 100 or len(items) >= data.get("total_count", 0):
            break
        page += 1
        time.sleep(2)
    return items[:cap]


_repo_cache = {}


def repo_info(full_name):
    if full_name not in _repo_cache:
        data = get(f"{API}/repos/{full_name}")
        _repo_cache[full_name] = {
            "stars": data.get("stargazers_count", 0),
            "description": (data.get("description") or "").strip(),
        }
    return _repo_cache[full_name]


def repo_of(item):
    return item["repository_url"].split("/repos/", 1)[1]


# ------------------------------------------------------------------ formatting

GITMOJI = re.compile(r"^\s*(:[a-z0-9_+-]+:\s*)+")
EMOJI = re.compile(
    r"^[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F]+\s*"
)


CONVENTIONAL = re.compile(
    r"^(fix|feat|chore|perf|refactor|docs|test|build|ci|style)"
    r"(\([^)]*\))?!?:\s*", re.I
)


def clean(title, key=None):
    """One uniform sentence per row: no gitmoji, no `fix(scope):` prefix."""
    if key and key in TITLE_OVERRIDES:
        title = TITLE_OVERRIDES[key]
    title = GITMOJI.sub("", title)
    title = EMOJI.sub("", title)
    title = CONVENTIONAL.sub("", title)
    title = re.sub(r"\s+", " ", title).strip()
    # Table cells, stray underscores and brackets would break the markdown.
    for char in ("|", "_", "[", "]"):
        title = title.replace(char, "\\" + char)
    # Capitalise prose, but never mangle an identifier like onCLS() or getINP().
    if re.match(r"^[a-z]+\b", title):
        title = title[:1].upper() + title[1:]
    return title


def day(stamp):
    return (stamp or "")[:10]


def stars_badge(full_name):
    return (f'<img src="https://img.shields.io/github/stars/{full_name}'
            f'?style=flat-square&label=%20&color=E3B341&labelColor=0D1117" alt="stars" />')


def human(n):
    """55075 -> 55k, 8727 -> 8.7k. Keeps a 1.1k repo distinct from a 1.6k one."""
    if n >= 10_000:
        return f"{n // 1000}k"
    if n >= 1000:
        return f"{n / 1000:.1f}k"
    return str(n)


# ---------------------------------------------------------------- block builders

def build_stats(merged, open_prs, issues, star_total, projects):
    parts = [
        BADGE.format(label="Merged%20PRs", value=len(merged), color="8957E5", logo="git"),
        BADGE.format(label="OSS%20Projects", value=projects, color="2EA043", logo="opensourceinitiative"),
        BADGE.format(label="Combined%20Stars", value=urllib.parse.quote(f"{star_total // 1000}k+"), color="E3B341", logo="github"),
        BADGE.format(label="Upstream%20Bugs%20Filed", value=len(issues), color="DA3633", logo="gitbook"),
        BADGE.format(label="In%20Review", value=len(open_prs), color="0EA5E9", logo="githubactions"),
    ]
    return "\n".join(f'<img src="{p}" alt="stat" />' for p in parts)


def build_merged(merged):
    rows = ["| Merged | Project | ★ | What shipped | PR |",
            "| :---: | :--- | :---: | :--- | :---: |"]
    for pr in merged:
        full_name = repo_of(pr)
        rows.append(
            f'| `{day(pr["closed_at"])}` '
            f'| **[{full_name}](https://github.com/{full_name})** '
            f'| `{human(repo_info(full_name)["stars"])}` '
            f'| {clean(pr["title"], f'{full_name}#{pr["number"]}')} '
            f'| [`#{pr["number"]}`]({pr["html_url"]}) |'
        )
    return "\n".join(rows)


def build_issues(issues):
    rows = ["| Reported | Project | The bug I found | Status |",
            "| :---: | :--- | :--- | :---: |"]
    for issue in issues:
        full_name = repo_of(issue)
        status = "✅ Fixed" if issue["state"] == "closed" else "🔎 Open"
        rows.append(
            f'| `{day(issue["created_at"])}` '
            f'| **[{full_name}](https://github.com/{full_name})** '
            f'| [{clean(issue["title"], f'{full_name}#{issue["number"]}')}]({issue["html_url"]}) '
            f'| {status} |'
        )
    return "\n".join(rows)


def build_activity(limit=6):
    """Newest public events, newest first -- same feel as GitHub's own feed."""

    def url_for(obj, repo, kind):
        # Event payloads occasionally ship without html_url; rebuild it.
        return obj.get("html_url") or (
            f'https://github.com/{repo}/{kind}/{obj.get("number", "")}'
        )

    events = get(f"{API}/users/{USER}/events/public", {"per_page": 100})
    lines, seen = [], set()
    for ev in events:
        repo = ev["repo"]["name"]
        repo_md = f"[{repo}](https://github.com/{repo})"
        payload, kind = ev.get("payload", {}), ev["type"]
        entry = None

        if kind == "PullRequestEvent":
            pr = payload.get("pull_request", {})
            if payload.get("action") == "closed" and pr.get("merged"):
                entry = f'🎉 Merged PR [#{pr["number"]}]({url_for(pr, repo, "pull")}) in {repo_md}'
            elif payload.get("action") == "opened":
                entry = f'💪 Opened PR [#{pr["number"]}]({url_for(pr, repo, "pull")}) in {repo_md}'
        elif kind == "IssuesEvent" and payload.get("action") in ("opened", "closed"):
            issue = payload.get("issue", {})
            icon = "❗" if payload["action"] == "opened" else "🔒"
            verb = "Opened" if payload["action"] == "opened" else "Closed"
            entry = f'{icon} {verb} issue [#{issue["number"]}]({url_for(issue, repo, "issues")}) in {repo_md}'
        elif kind == "IssueCommentEvent" and payload.get("action") == "created":
            issue = payload.get("issue", {})
            comment = payload.get("comment", {})
            entry = f'🗣 Commented on [#{issue["number"]}]({url_for(comment, repo, "issues")}) in {repo_md}'
        elif kind == "PullRequestReviewEvent":
            pr = payload.get("pull_request", {})
            entry = f'👀 Reviewed [#{pr["number"]}]({url_for(pr, repo, "pull")}) in {repo_md}'
        elif kind == "CreateEvent" and payload.get("ref_type") == "repository":
            entry = f'🎊 Created new repository {repo_md}'

        if entry and "#None" not in entry and entry not in seen:
            seen.add(entry)
            lines.append(entry)
        if len(lines) == limit:
            break

    if not lines:
        return "_Quiet week — check the merged PRs above._"
    return "\n".join(f"{i}. {line}" for i, line in enumerate(lines, 1))


# ------------------------------------------------------------------------ inject

def inject(readme, name, body):
    start, end = f"<!--START_SECTION:{name}-->", f"<!--END_SECTION:{name}-->"
    if start not in readme:
        print(f"  ! marker '{name}' missing from README, skipped")
        return readme
    return re.sub(
        re.escape(start) + ".*?" + re.escape(end),
        lambda _: f"{start}\n{body}\n{end}",
        readme,
        flags=re.S,
    )


def main():
    print("Fetching contributions...")
    merged = search(f"author:{USER} is:pr is:merged is:public -user:{USER}")
    # Open PRs are no longer tabled, but still drive the "In Review" badge.
    open_prs = search(f"author:{USER} is:pr is:open is:public -user:{USER}")
    raw_issues = search(
        f"author:{USER} is:issue is:public -user:{USER} created:>={ISSUES_SINCE}"
    )

    merged.sort(key=lambda p: p["closed_at"] or "", reverse=True)
    open_prs.sort(key=lambda p: p["created_at"], reverse=True)

    # Repos I actually contribute code to, plus a couple I only file bugs in.
    worked_in = {repo_of(p) for p in merged} | {repo_of(p) for p in open_prs}
    allowed = worked_in | EXTRA_ISSUE_REPOS
    issues = [
        i for i in raw_issues
        if repo_of(i) in allowed
        and repo_info(repo_of(i))["stars"] >= MIN_STARS
        and not NOT_A_BUG.match(i["title"])
    ]
    issues.sort(key=lambda i: i["created_at"], reverse=True)

    merged_repos = {repo_of(p) for p in merged}
    star_total = sum(repo_info(r)["stars"] for r in merged_repos)

    print(f"  merged={len(merged)} open={len(open_prs)} issues={len(issues)} "
          f"repos={len(merged_repos)} stars={star_total}")

    readme = open(README, encoding="utf-8").read()
    readme = inject(readme, "stats",
                    build_stats(merged, open_prs, issues, star_total, len(merged_repos)))
    readme = inject(readme, "oss", build_merged(merged))
    readme = inject(readme, "issues", build_issues(issues))
    readme = inject(readme, "activity", build_activity())
    open(README, "w", encoding="utf-8").write(readme)
    print("README.md updated.")


if __name__ == "__main__":
    try:
        main()
    except urllib.error.HTTPError as err:
        print(f"GitHub API error {err.code}: {err.reason}", file=sys.stderr)
        sys.exit(1)
