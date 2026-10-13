# acli Setup Guide for RHDH Feature Docs

This guide walks you through setting up acli (Atlassian CLI) for the rhdh-feature-docs skill.

## What is acli?

acli is the official Atlassian Command Line Interface for interacting with Jira, Confluence, and other Atlassian products. It provides a secure, robust way to fetch Jira data without needing to manage API credentials in environment files.

## Why Use acli?

1. **Security**: Credentials stored in OS keyring (macOS Keychain, Windows Credential Manager, Linux Secret Service)
2. **Standard Tool**: Used by the official RHDH team for all Jira operations
3. **Native JQL Support**: Built-in support for Jira Query Language (JQL)
4. **Maintained by Atlassian**: Official tool, regularly updated
5. **No HTTP Libraries Needed**: Python scripts use standard library only (subprocess)

## Installation

### Download from Official Source

1. Visit: https://bobswift.atlassian.net/wiki/spaces/ACLI/overview
2. Download the appropriate package for your OS
3. Follow the installation instructions for your platform

### Verify Installation

```bash
acli --version
```

Expected output:
```
ACLI version X.X.X
```

## Authentication Setup

### Step 1: Create Jira API Token

1. Go to: https://id.atlassian.com/manage-profile/security/api-tokens
2. Click "Create API token"
3. Give it a descriptive name (e.g., "rhdh-feature-docs-skill")
4. Copy the token (you won't be able to see it again!)

### Step 2: Authenticate acli

Run the authentication command:

```bash
acli jira auth login --site redhat.atlassian.net --email <your-email@redhat.com> --token
```

When prompted:
- **Site**: `redhat.atlassian.net` (already in command)
- **Email**: Your Red Hat email address (already in command)
- **Token**: Paste the API token you just created

Expected output:
```
Successfully authenticated to redhat.atlassian.net
```

### Step 3: Verify Authentication

Test that acli can access Jira:

```bash
acli jira project list --recent 1
```

Expected output (something like):
```
Project: RHDHPLAN
Name: Red Hat Developer Hub Planning
...
```

## Verify RHDH Project Access

Test access to the three main RHDH Jira projects:

```bash
# Test RHDHPLAN access
acli jira project view --key RHDHPLAN

# Test RHIDP access
acli jira project view --key RHIDP

# Test RHDHBUGS access
acli jira project view --key RHDHBUGS
```

All three should return project information without errors.

## Run the Validation Script

The skill includes an automated validation script:

```bash
python3 "$SKILL/scripts/setup_acli.py"
```

Expected output:
```
Validating acli setup for rhdh-feature-docs...

✓ acli is installed
  Version: ACLI version X.X.X
✓ acli is authenticated to Jira

Testing access to RHDH projects:
  ✓ RHDHPLAN - accessible
  ✓ RHIDP - accessible
  ✓ RHDHBUGS - accessible

✓ All checks passed! The skill is ready to use.
```

## Testing the Jira Client

Test fetching a Jira issue:

```bash
python3 "$SKILL/scripts/jira_acli.py" RHDHPLAN-1254
```

This should output JSON with the epic details.

Test fetching with child issues:

```bash
python3 "$SKILL/scripts/jira_acli.py" RHDHPLAN-1235 --children
```

This should output JSON including a "children" array with child issue details.

## Troubleshooting

### acli not found

**Error**: `acli: command not found`

**Solution**:
1. Ensure acli is installed
2. Check that acli is in your PATH
3. Try running: `which acli` to see if it's accessible

### Authentication Failed

**Error**: `✗ acli authentication failed`

**Solutions**:
1. Check your API token is still valid: https://id.atlassian.com/manage-profile/security/api-tokens
2. Revoke and create a new token if needed
3. Re-run authentication: `acli jira auth login --site redhat.atlassian.net --email <email> --token`

### Project Not Accessible

**Error**: `✗ RHDHPLAN - not accessible`

**Solutions**:
1. Ensure you have permissions to view the project in Jira web interface
2. Try logging out and back in with acli
3. Contact your Jira administrator if permissions issues persist

### Timeout Errors

**Error**: `Search timeout for JQL: ...`

**Solutions**:
1. Check your internet connection
2. Try the query directly with acli: `acli jira workitem search --jql "project = RHDHPLAN" --limit 10`
3. Simplify the JQL query if it's too complex

## Credential Management

### Where Are Credentials Stored?

acli stores credentials securely in your operating system's credential manager:

- **macOS**: Keychain Access
- **Windows**: Windows Credential Manager
- **Linux**: Secret Service (e.g., GNOME Keyring, KDE Wallet)

### Viewing Stored Credentials

You can view (but not see the token) in:

- **macOS**: Open "Keychain Access" app → Search for "atlassian"
- **Windows**: Control Panel → Credential Manager → Windows Credentials
- **Linux**: Depends on your desktop environment

### Revoking Access

To remove acli credentials:

```bash
acli jira auth logout --site redhat.atlassian.net
```

To revoke the API token entirely:
1. Go to: https://id.atlassian.com/manage-profile/security/api-tokens
2. Find your token
3. Click "Revoke"

## The `JIRA_API_TOKEN` environment variable

`acli` keeps its own credentials in the OS keyring, but the skill's remote/web-link
PR discovery (`jira_acli.py --pull-requests` / `--remote-links`) calls the Jira REST
API directly and reads a token from the `JIRA_API_TOKEN` environment variable. This
is separate from the acli keyring entry.

Set it for the session without writing it to a file the skill reads, and without
leaving it in shell history:

```bash
# Prompt for the token (input is not echoed) and export it:
read -rs JIRA_API_TOKEN && export JIRA_API_TOKEN
```

### Never print the token

The scripts read `JIRA_API_TOKEN` straight from the environment and base64-encode it
into the Authorization header — they never display it. Nothing in a run should print
it either. To check whether it is set, test **presence only**:

```bash
[ -n "$JIRA_API_TOKEN" ] && echo "token present" || echo "token missing"
```

Do **not** use `echo "$JIRA_API_TOKEN"` or `echo "${JIRA_API_TOKEN:-no}"`. The
`${VAR:-default}` and `${VAR:=default}` forms expand to the token's value when it is
set, so they leak it. Only `${VAR:+set}` and the `-n`/`-z` tests are safe. If a token
ever reaches a terminal, log, output file, or generated document, treat it as
compromised and revoke it at
https://id.atlassian.com/manage-profile/security/api-tokens.

## Security Best Practices

1. **Use Descriptive Token Names**: Name tokens after their purpose (e.g., "rhdh-docs-skill-2024")
2. **Rotate Tokens Regularly**: Create new tokens periodically and revoke old ones
3. **Don't Share Tokens**: Each person should use their own API token
4. **Monitor Token Usage**: Check your Atlassian account security page regularly
5. **Revoke Unused Tokens**: Clean up tokens you no longer need
6. **Never Print or Interpolate a Token**: Test presence with `-n`/`${VAR:+set}`;
   never expand the value into an `echo`, log, output file, or generated document

## JQL Examples

Once acli is set up, you can use JQL (Jira Query Language) to search issues:

### Find epics in RHDHPLAN:
```bash
acli jira workitem search --jql "project = RHDHPLAN AND issuetype = Epic" --limit 10
```

### Find child issues of an epic:
```bash
acli jira workitem search --jql "parent = RHDHPLAN-1254" --limit 100
```

### Find issues assigned to you:
```bash
acli jira workitem search --jql "assignee = currentUser() AND status != Done" --limit 20
```

### Find recently updated issues:
```bash
acli jira workitem search --jql "project = RHIDP AND updated >= -7d ORDER BY updated DESC" --limit 10
```

## Advanced Configuration

### Custom Timeout

If you experience timeouts, you can increase the timeout in `jira_acli.py`:

```python
# Default timeout is 30 seconds
result = subprocess.run(
    ["acli", "jira", "workitem", "view", issue_key],
    timeout=60  # Increase to 60 seconds
)
```

### Pagination

For large result sets, use pagination:

```bash
# Get first 100 results
acli jira workitem search --jql "project = RHDHPLAN" --limit 100 --offset 0

# Get next 100 results
acli jira workitem search --jql "project = RHDHPLAN" --limit 100 --offset 100
```

## Getting Help

- **acli Documentation**: https://bobswift.atlassian.net/wiki/spaces/ACLI/overview
- **Jira REST API Docs**: https://developer.atlassian.com/cloud/jira/platform/rest/v3/
- **JQL Reference**: https://support.atlassian.com/jira-service-management-cloud/docs/use-advanced-search-with-jira-query-language-jql/
- **Red Hat Internal Support**: Contact #rhdh-team on Slack

## Summary

You're all set! With acli configured, the rhdh-feature-docs skill can:

✅ Fetch Jira epics with full details  
✅ Discover child issues automatically via JQL  
✅ Search issues across RHDH projects  
✅ Use secure credential storage (OS keyring)  
✅ Align with official RHDH team practices  

No more `.env` files, no more managing API credentials manually!
