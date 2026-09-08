#!/usr/bin/env python3
"""
Fetch RHDH documentation from the official GitHub repository.
No Playwright needed - reads AsciiDoc files directly from git.
"""

import os
import shutil
import subprocess
import sys
import tempfile
from typing import Dict, List, Optional


class RHDHDocsClient:
    """Fetch RHDH documentation from GitHub repository."""

    REPO_URL = "https://github.com/redhat-developer/red-hat-developers-documentation-rhdh.git"
    DEFAULT_BRANCH = "release-1.10"  # Latest release as of 2026-09-02

    def __init__(self, branch: str = DEFAULT_BRANCH):
        """
        Initialize client.

        Args:
            branch: Git branch to clone (default: release-1.10)
        """
        self.branch = branch
        self.repo_dir = None

    def clone_repo(self, target_dir: Optional[str] = None) -> str:
        """
        Clone the RHDH docs repository.

        Args:
            target_dir: Directory to clone into (default: temp directory)

        Returns:
            Path to cloned repository
        """
        if target_dir is None:
            target_dir = tempfile.mkdtemp(prefix="rhdh-docs-")

        print(f"Cloning RHDH docs repository (branch: {self.branch})...", file=sys.stderr)

        try:
            result = subprocess.run(
                [
                    "git",
                    "clone",
                    "--depth",
                    "1",
                    "--branch",
                    self.branch,
                    self.REPO_URL,
                    target_dir,
                ],
                capture_output=True,
                text=True,
                timeout=60,
            )

            if result.returncode != 0:
                raise Exception(f"Git clone failed: {result.stderr}")

            self.repo_dir = target_dir
            print(f"✓ Repository cloned to: {target_dir}", file=sys.stderr)
            return target_dir

        except subprocess.TimeoutExpired:
            raise Exception("Git clone timed out (60s)")

    def list_titles(self) -> List[str]:
        """
        List available documentation titles.

        Returns:
            List of title names (e.g., ['discover_about-rhdh', 'install_installing-rhdh-on-ocp'])
        """
        if not self.repo_dir:
            raise Exception("Repository not cloned. Call clone_repo() first.")

        titles_dir = os.path.join(self.repo_dir, "titles")
        if not os.path.exists(titles_dir):
            return []

        titles = []
        for item in os.listdir(titles_dir):
            item_path = os.path.join(titles_dir, item)
            if os.path.isdir(item_path):
                titles.append(item)

        return sorted(titles)

    def find_title_by_keyword(self, keyword: str) -> List[str]:
        """
        Find titles matching a keyword.

        Args:
            keyword: Search term (e.g., "plugin", "install", "configure")

        Returns:
            List of matching title names
        """
        titles = self.list_titles()
        keyword_lower = keyword.lower()
        return [t for t in titles if keyword_lower in t.lower()]

    def read_title(self, title_name: str) -> Optional[str]:
        """
        Read a documentation title's master file.

        Args:
            title_name: Title directory name (e.g., 'discover_about-rhdh')

        Returns:
            Content of the master.adoc file, or None if not found
        """
        if not self.repo_dir:
            raise Exception("Repository not cloned. Call clone_repo() first.")

        master_file = os.path.join(self.repo_dir, "titles", title_name, "master.adoc")

        if not os.path.exists(master_file):
            print(f"Master file not found: {master_file}", file=sys.stderr)
            return None

        with open(master_file, "r", encoding="utf-8") as f:
            return f.read()

    def read_module(self, module_path: str) -> Optional[str]:
        """
        Read a documentation module.

        Args:
            module_path: Relative path to module (e.g., 'modules/discover_about-rhdh/con-understanding-internal-developer-platforms.adoc')

        Returns:
            Content of the module file, or None if not found
        """
        if not self.repo_dir:
            raise Exception("Repository not cloned. Call clone_repo() first.")

        full_path = os.path.join(self.repo_dir, module_path)

        if not os.path.exists(full_path):
            print(f"Module not found: {full_path}", file=sys.stderr)
            return None

        with open(full_path, "r", encoding="utf-8") as f:
            return f.read()

    def get_title_with_modules(self, title_name: str) -> Dict[str, str]:
        """
        Get a title and all its included modules.

        Args:
            title_name: Title directory name

        Returns:
            Dict with 'master' content and 'modules' dict {module_path: content}
        """
        master_content = self.read_title(title_name)
        if not master_content:
            return {}

        result = {"title": title_name, "master": master_content, "modules": {}}

        # Parse include directives
        for line in master_content.split("\n"):
            if line.strip().startswith("include::") and "::" in line:
                # Extract path: include::modules/path/file.adoc[...] -> modules/path/file.adoc
                include_path = line.split("include::")[1].split("[")[0].strip()

                if include_path.startswith("modules/"):
                    module_content = self.read_module(include_path)
                    if module_content:
                        result["modules"][include_path] = module_content

        return result

    def cleanup(self):
        """Remove cloned repository."""
        if self.repo_dir and os.path.exists(self.repo_dir):
            shutil.rmtree(self.repo_dir)
            print(f"✓ Cleaned up: {self.repo_dir}", file=sys.stderr)
            self.repo_dir = None


def main():
    """CLI interface for testing."""
    import argparse

    parser = argparse.ArgumentParser(description="Fetch RHDH documentation from GitHub")
    parser.add_argument(
        "--branch",
        default=RHDHDocsClient.DEFAULT_BRANCH,
        help="Git branch to use (default: release-1.10)",
    )
    parser.add_argument("--list", action="store_true", help="List all available titles")
    parser.add_argument("--search", metavar="KEYWORD", help="Search titles by keyword")
    parser.add_argument(
        "--title", metavar="TITLE_NAME", help="Read a specific title (e.g., discover_about-rhdh)"
    )
    parser.add_argument(
        "--with-modules", action="store_true", help="Include all modules when reading a title"
    )

    args = parser.parse_args()

    client = RHDHDocsClient(branch=args.branch)

    try:
        # Clone repository
        client.clone_repo()

        if args.list:
            titles = client.list_titles()
            print(f"\nAvailable titles ({len(titles)}):")
            for title in titles:
                print(f"  - {title}")

        elif args.search:
            matches = client.find_title_by_keyword(args.search)
            print(f"\nTitles matching '{args.search}' ({len(matches)}):")
            for match in matches:
                print(f"  - {match}")

        elif args.title:
            if args.with_modules:
                data = client.get_title_with_modules(args.title)
                if data:
                    print("\n=== MASTER FILE ===")
                    print(data["master"])
                    print(f"\n=== MODULES ({len(data['modules'])}) ===")
                    for module_path, content in data["modules"].items():
                        print(f"\n--- {module_path} ---")
                        print(content)
                else:
                    print(f"Title not found: {args.title}", file=sys.stderr)
                    sys.exit(1)
            else:
                content = client.read_title(args.title)
                if content:
                    print(content)
                else:
                    print(f"Title not found: {args.title}", file=sys.stderr)
                    sys.exit(1)

        else:
            parser.print_help()

    finally:
        # Clean up
        client.cleanup()


if __name__ == "__main__":
    main()
