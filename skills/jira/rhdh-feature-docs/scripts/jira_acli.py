#!/usr/bin/env python3
"""
Jira integration using acli (Atlassian CLI).
Uses standard library only - no external HTTP dependencies.
"""

import base64
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from typing import Dict, List, Optional

# Matches a GitHub pull request URL, e.g.
# https://github.com/org/repo/pull/1234
PR_URL_RE = re.compile(r"https://github\.com/[A-Za-z0-9_.\-]+/[A-Za-z0-9_.\-]+/pull/\d+")


class JiraClient:
    """Jira client using acli subprocess calls."""

    def __init__(self):
        """Initialize client. Assumes acli is installed and authenticated."""
        self._verify_acli()
        self._site: Optional[str] = None
        self._email: Optional[str] = None

    def _verify_acli(self):
        """Verify acli is installed and accessible."""
        try:
            result = subprocess.run(
                ["acli", "--version"], capture_output=True, text=True, timeout=5
            )
            if result.returncode != 0:
                raise Exception("acli is installed but returned error")
        except FileNotFoundError:
            raise Exception(
                "acli not found. Please install from: "
                "https://bobswift.atlassian.net/wiki/spaces/ACLI/overview"
            )
        except subprocess.TimeoutExpired:
            raise Exception("acli command timed out")

    def fetch_issue(self, issue_key: str) -> Optional[Dict]:
        """
        Fetch a single Jira issue with all fields.

        Args:
            issue_key: Jira issue key (e.g., "RHDHPLAN-1234")

        Returns:
            Issue data as dict, or None if not found
        """
        try:
            result = subprocess.run(
                ["acli", "jira", "workitem", "view", issue_key, "--fields", "*all", "--json"],
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode != 0:
                print(f"Failed to fetch {issue_key}: {result.stderr}", file=sys.stderr)
                return None

            return json.loads(result.stdout)

        except subprocess.TimeoutExpired:
            print(f"Timeout fetching {issue_key}", file=sys.stderr)
            return None
        except json.JSONDecodeError as e:
            print(f"Invalid JSON from acli: {e}", file=sys.stderr)
            return None

    def search_issues(self, jql: str, max_results: int = 100) -> List[Dict]:
        """
        Search issues using JQL.

        Args:
            jql: Jira Query Language string
            max_results: Maximum number of results to return

        Returns:
            List of issue dicts
        """
        try:
            result = subprocess.run(
                [
                    "acli",
                    "jira",
                    "workitem",
                    "search",
                    "--jql",
                    jql,
                    "--limit",
                    str(max_results),
                    "--json",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode != 0:
                print(f"Search failed: {result.stderr}", file=sys.stderr)
                return []

            data = json.loads(result.stdout)
            # acli may return a top-level array of issues, or a dict with an
            # 'issues' array. Handle both shapes.
            if isinstance(data, list):
                return data
            return data.get("issues", []) if isinstance(data, dict) else []

        except subprocess.TimeoutExpired:
            print(f"Search timeout for JQL: {jql}", file=sys.stderr)
            return []
        except json.JSONDecodeError as e:
            print(f"Invalid JSON from acli search: {e}", file=sys.stderr)
            return []

    def get_child_issues(self, parent_key: str) -> List[Dict]:
        """
        Get all child issues of a parent epic/feature using JQL.

        Args:
            parent_key: Parent issue key

        Returns:
            List of child issue dicts
        """
        jql = f"parent = {parent_key}"
        return self.search_issues(jql)

    def enrich_issue_with_children(self, issue_data: Dict) -> Dict:
        """
        Enrich issue data with child issues.

        Args:
            issue_data: Issue dict from fetch_issue()

        Returns:
            Same dict with 'children' field added
        """
        issue_key = issue_data.get("key")
        if not issue_key:
            return issue_data

        children = self.get_child_issues(issue_key)

        # Enrich each child with full details
        enriched_children = []
        for child in children:
            child_key = child.get("key")
            if child_key:
                full_child = self.fetch_issue(child_key)
                if full_child:
                    enriched_children.append(full_child)

        issue_data["children"] = enriched_children
        return issue_data

    def _acli_identity(self):
        """Read the authenticated site and email from `acli jira auth status`.

        Neither value is a secret. Cached for the client's lifetime.
        """
        if self._site is None or self._email is None:
            try:
                result = subprocess.run(
                    ["acli", "jira", "auth", "status"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                for line in result.stdout.splitlines():
                    stripped = line.strip()
                    low = stripped.lower()
                    if low.startswith("site:"):
                        self._site = stripped.split(":", 1)[1].strip()
                    elif low.startswith("email:"):
                        self._email = stripped.split(":", 1)[1].strip()
            except (subprocess.SubprocessError, OSError):
                pass
        return self._site, self._email

    def _rest_auth(self):
        """Resolve (base_url, email, token) for authenticated REST calls.

        The token is read only from the JIRA_API_TOKEN environment variable and
        is never logged. Site and email come from JIRA_BASE_URL / JIRA_EMAIL when
        set, otherwise from `acli jira auth status`. Returns None when the token
        or identity is unavailable.
        """
        token = os.environ.get("JIRA_API_TOKEN")
        if not token:
            return None
        base = os.environ.get("JIRA_BASE_URL")
        email = os.environ.get("JIRA_EMAIL")
        if not base or not email:
            site, acct = self._acli_identity()
            base = base or (f"https://{site}" if site else None)
            email = email or acct
        if not base or not email:
            return None
        return base.rstrip("/"), email, token

    def get_remote_links(self, issue_key: str) -> List[Dict]:
        """Fetch remote (web) links for an issue, such as Git Pull Request links.

        Remote links are NOT returned by `acli workitem view`; they require the
        Jira REST remotelink endpoint. Returns a list of
        {title, url, relationship} dicts, or [] when unavailable.
        """
        auth = self._rest_auth()
        if not auth:
            print(
                "Remote links need JIRA_API_TOKEN (and a resolvable site/email); skipping.",
                file=sys.stderr,
            )
            return []
        base, email, token = auth
        url = f"{base}/rest/api/3/issue/{issue_key}/remotelink"
        credential = base64.b64encode(f"{email}:{token}".encode()).decode()
        request = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Basic {credential}",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                data = json.loads(response.read().decode())
        except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as e:
            print(f"Failed to fetch remote links for {issue_key}: {e}", file=sys.stderr)
            return []

        links = []
        for link in data if isinstance(data, list) else []:
            obj = link.get("object", {}) or {}
            links.append(
                {
                    "title": obj.get("title"),
                    "url": obj.get("url"),
                    "relationship": link.get("relationship"),
                }
            )
        return links

    def get_pull_requests(self, issue_data: Dict) -> List[Dict]:
        """Collect GitHub pull request links attached to a single issue.

        Pull requests may be attached as remote/web links (the Git Pull Request
        panel) or mentioned in the description, comments, or custom fields. This
        merges both, deduplicated by URL, recording where each was found.
        """
        issue_key = issue_data.get("key")
        found: Dict[str, set] = {}

        # 1) Remote (web) links — the authoritative Git Pull Request source.
        if issue_key:
            for link in self.get_remote_links(issue_key):
                url = link.get("url") or ""
                if PR_URL_RE.search(url):
                    found.setdefault(url, set()).add("web-link")

        # 2) URLs mentioned inside issue fields (description, comments, custom).
        fields = issue_data.get("fields", {}) or {}
        for field_name, value in fields.items():
            if value is None:
                continue
            for url in PR_URL_RE.findall(json.dumps(value)):
                source = field_name if field_name in ("comment", "description") else "field"
                found.setdefault(url, set()).add(source)

        return [{"url": url, "sources": sorted(sources)} for url, sources in sorted(found.items())]

    def collect_feature_pull_requests(self, root_key: str, max_depth: int = 3) -> List[Dict]:
        """Walk a feature tree and collect pull requests per issue.

        Traverses `root_key` and its descendants via the `parent` field down to
        `max_depth` levels, returning one entry per issue that has at least one
        pull request, with its key, type, status, summary, depth, and PRs.
        """
        results: List[Dict] = []
        visited: set = set()

        def walk(key: str, depth: int):
            if key in visited or depth > max_depth:
                return
            visited.add(key)
            issue = self.fetch_issue(key)
            if not issue:
                return
            prs = self.get_pull_requests(issue)
            if prs:
                fields = issue.get("fields", {}) or {}
                results.append(
                    {
                        "key": key,
                        "type": (fields.get("issuetype") or {}).get("name"),
                        "status": (fields.get("status") or {}).get("name"),
                        "summary": fields.get("summary"),
                        "depth": depth,
                        "pull_requests": prs,
                    }
                )
            for child in self.get_child_issues(key):
                child_key = child.get("key")
                if child_key:
                    walk(child_key, depth + 1)

        walk(root_key, 0)
        return results


def main():
    """CLI interface for testing."""
    import argparse

    parser = argparse.ArgumentParser(description="Fetch Jira issues via acli")
    parser.add_argument("issue_key", help="Jira issue key (e.g., RHDHPLAN-1234)")
    parser.add_argument("--children", action="store_true", help="Include child issues")
    parser.add_argument(
        "--remote-links",
        action="store_true",
        help="List remote/web links (e.g. Git Pull Request links) for the issue",
    )
    parser.add_argument(
        "--pull-requests",
        action="store_true",
        help="Walk the feature tree and collect GitHub pull requests per issue",
    )

    args = parser.parse_args()

    client = JiraClient()

    if args.pull_requests:
        print(json.dumps(client.collect_feature_pull_requests(args.issue_key), indent=2))
        return

    if args.remote_links:
        print(json.dumps(client.get_remote_links(args.issue_key), indent=2))
        return

    issue = client.fetch_issue(args.issue_key)

    if not issue:
        print(f"Issue {args.issue_key} not found", file=sys.stderr)
        sys.exit(1)

    if args.children:
        issue = client.enrich_issue_with_children(issue)

    print(json.dumps(issue, indent=2))


if __name__ == "__main__":
    main()
