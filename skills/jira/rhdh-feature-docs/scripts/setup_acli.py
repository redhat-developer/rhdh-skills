#!/usr/bin/env python3
"""
Validate acli installation and authentication.
Run this before using the skill.
"""

import subprocess
import sys


def check_acli_installed():
    """Check if acli is installed."""
    try:
        result = subprocess.run(["acli", "--version"], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            print("✓ acli is installed")
            print(f"  Version: {result.stdout.strip()}")
            return True
        else:
            print("✗ acli command failed")
            return False
    except FileNotFoundError:
        print("✗ acli not found in PATH")
        print("\nInstallation instructions:")
        print("  Download from: https://bobswift.atlassian.net/wiki/spaces/ACLI/overview")
        return False
    except subprocess.TimeoutExpired:
        print("✗ acli command timed out")
        return False


def check_acli_authenticated():
    """Check if acli is authenticated to Jira."""
    try:
        result = subprocess.run(
            ["acli", "jira", "project", "list", "--recent", "1"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            print("✓ acli is authenticated to Jira")
            return True
        else:
            print("✗ acli authentication failed")
            print("\nAuthentication instructions:")
            print(
                "  Run: acli jira auth login --site redhat.atlassian.net --email <your-email> --token"
            )
            print(
                "  You'll need a Jira API token from: https://id.atlassian.com/manage-profile/security/api-tokens"
            )
            return False
    except subprocess.TimeoutExpired:
        print("✗ Authentication check timed out")
        return False


def test_rhdh_project_access():
    """Test access to RHDH Jira projects."""
    projects = ["RHDHPLAN", "RHIDP", "RHDHBUGS"]

    print("\nTesting access to RHDH projects:")
    for project in projects:
        try:
            result = subprocess.run(
                ["acli", "jira", "project", "view", "--key", project],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                print(f"  ✓ {project} - accessible")
            else:
                print(f"  ✗ {project} - not accessible")
        except subprocess.TimeoutExpired:
            print(f"  ✗ {project} - timeout")


def main():
    """Run all validation checks."""
    print("Validating acli setup for rhdh-feature-docs...\n")

    acli_ok = check_acli_installed()
    if not acli_ok:
        sys.exit(1)

    auth_ok = check_acli_authenticated()
    if not auth_ok:
        sys.exit(1)

    test_rhdh_project_access()

    print("\n✓ All checks passed! The skill is ready to use.")


if __name__ == "__main__":
    main()
