# Configure Google Workspace access

Release and test-plan workflows use `gog`, which owns credentials in its native store. Setup reports
capability status only.

## Release access with gog

1. Confirm `gog` is on `PATH`. If it is missing, install `gogcli` using the supported package
   instructions at <https://gogcli.sh>.
2. Import the user's OAuth client file directly into the CLI's credential store, then remove any
   temporary copy according to the user's credential-handling policy:

   ```bash
   gog auth credentials <client-secret-file>
   ```

3. Start browser-mediated authorization for the account and required services:

   ```bash
   gog auth add <account> --services sheets,docs,drive,calendar
   ```

4. Verify access with the consuming release workflow's read-only `gog sheets metadata ... --json`
   check. Do not report the account identifier or returned document data.

## Test-plan access

Run `python scripts/check_gsheets.py` from `/rhdh-test-plan-review` after the `gog` setup above. The check
must read schedule metadata through `gog`; it never prints or copies an OAuth token.

The setup doctor reports `gog` installation status. Report only tool presence, authentication
status, and target-access status. Do not include account names, client-secret paths, access tokens,
or refresh tokens.
