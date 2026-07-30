#!/usr/bin/env bash
# Auto-fills the <!--START_SECTION:oss--> block in README.md with your merged
# PRs to repos you DON'T own -- i.e. real open-source contributions.
set -euo pipefail

USER="suhailopensource"
README="README.md"

# JSON array of {repo, number, title, url} -> markdown bullets.
to_bullets() {
  jq -r '.[] | "- **[\(.repo)](https://github.com/\(.repo))** [#\(.number)](\(.url)) — \(.title | if length > 70 then .[0:67] + "..." else . end)"'
}

# Merged PRs authored by USER in repos NOT owned by USER (external OSS work).
merged=$(gh api -X GET search/issues \
  -f q="author:${USER} is:pr is:merged -user:${USER}" -f per_page=15 \
  --jq '[.items[] | {repo:(.repository_url|sub("https://api.github.com/repos/";"")), number:.number, title:.title, url:.html_url}]')

merged_md=$(echo "$merged" | to_bullets)
[ -z "$merged_md" ] && merged_md="- _Contributions loading..._"

# Inject between the markers, leaving the rest of README untouched.
python3 - "$README" "$merged_md" <<'PY'
import re, sys
path, body = sys.argv[1], sys.argv[2]
s = open(path, encoding="utf-8").read()
new = re.sub(
    r"(<!--START_SECTION:oss-->).*?(<!--END_SECTION:oss-->)",
    lambda m: m.group(1) + "\n" + body + "\n" + m.group(2),
    s, flags=re.S,
)
open(path, "w", encoding="utf-8").write(new)
print("OSS merged-PR section updated.")
PY
