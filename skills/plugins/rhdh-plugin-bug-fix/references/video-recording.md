# Video Recording: Playwright Capture & Conversion

How to capture before/after screen recordings for bug fix PRs. Reference this in Steps 3, 4, 6, and 7.

## Playwright Video Configuration

The reproduction test must **always create its own browser context** with `recordVideo` to guarantee video capture regardless of how the workspace's e2e infrastructure manages contexts:

```typescript
test('repro', async ({ browser }) => {
  const context = await browser.newContext({
    recordVideo: { dir: 'test-results/', size: { width: 1280, height: 720 } },
  });
  const page = await context.newPage();

  // ... test steps ...

  await context.close(); // finalizes the video file
});
```

- **`recordVideo.dir`** — directory where Playwright saves the `.webm` file.
- **`size`** — 1280x720 gives good quality at reasonable file size. Matches most laptop viewports.
- **`context.close()`** — MUST be called to finalize the video. Without it the file may be incomplete.

All rhdh-plugins workspaces use `@playwright/test` >= 1.60.0, which supports this config.

### Why not `test.use({ video: ... })`?

`test.use()` only applies to Playwright's auto-created contexts. Many rhdh-plugins workspaces (e.g., `intelligent-assistant`) manually create contexts in `beforeAll` helpers, which bypasses `test.use()` entirely. By always creating our own context with `recordVideo`, we avoid this pitfall.

## Where Videos Land

Playwright saves videos to the `test-results/` directory inside the workspace:

```
workspaces/<workspace>/test-results/
└── <test-describe-title>-<test-title>-<browser>/
    └── video.webm
```

The exact path depends on the test title. After running, find the video:

```bash
find test-results -name "video.webm" -type f
```

## Capturing Before/After Videos

### Before fix (Step 4)

After the reproduction test **fails** (bug is present):

```bash
mkdir -p e2e-tests/_repro-artifacts
cp test-results/*/video.webm e2e-tests/_repro-artifacts/before-fix.webm
```

### After fix (Step 6)

Clean the test results first, then re-run:

```bash
rm -rf test-results/
APP_MODE=legacy npx playwright test e2e-tests/_repro-<KEY>.test.ts --project=en
cp test-results/*/video.webm e2e-tests/_repro-artifacts/after-fix.webm
```

## Converting to GIF

GitHub PR descriptions support inline images (PNG, GIF, JPEG) but NOT inline `.webm` video. Convert to GIF for embedding.

### With ffmpeg (recommended)

```bash
ffmpeg -i e2e-tests/_repro-artifacts/before-fix.webm \
  -vf "fps=15,scale=800:-1,setpts=1.5*PTS" -loop 0 \
  e2e-tests/_repro-artifacts/before-fix.gif

ffmpeg -i e2e-tests/_repro-artifacts/after-fix.webm \
  -vf "fps=15,scale=800:-1,setpts=1.5*PTS" -loop 0 \
  e2e-tests/_repro-artifacts/after-fix.gif
```

Options explained:

- `fps=15` — 15 frames per second for smooth playback
- `scale=800:-1` — scale width to 800px, maintain aspect ratio
- `setpts=1.5*PTS` — slow playback to 1.5x duration so transitions are visible to human reviewers
- `-loop 0` — loop the GIF infinitely

### Check if ffmpeg is available

```bash
which ffmpeg >/dev/null 2>&1 && echo "available" || echo "not found"
```

### Without ffmpeg (fallback)

If `ffmpeg` is not installed:

1. Keep the `.webm` files as-is.
2. After the PR is created, upload the `.webm` files as PR comment attachments.
3. Reference them in the PR body as download links rather than inline images.
4. Inform the user: "Install `ffmpeg` for inline GIF previews in PRs: `brew install ffmpeg` (macOS) or `sudo apt install ffmpeg` (Linux)."

## Embedding in PR Description

### Automated approach (preferred) — Upload to dedicated `screenrecordings` branch

Hand the GIF paths to `/rhdh-pr-create` as the before and after recordings. It
uploads them to a dedicated `screenrecordings` branch on the user's fork,
keeping them out of the feature diff and upstream `main`.

Files are stored with issue-specific paths to avoid collisions across bug fixes:

```
screenrecordings/<workspace>-<ISSUE_ID>/before-fix.gif
screenrecordings/<workspace>-<ISSUE_ID>/after-fix.gif
```

Where `<ISSUE_ID>` is the Jira key (e.g., `RHDHBUGS-2911`) or GitHub issue number (e.g., `9834`).

```bash
GIF_B64=$(base64 -i e2e-tests/_repro-artifacts/before-fix.gif)
gh api --method PUT \
  "repos/<fork-owner>/<repo-name>/contents/screenrecordings/<workspace>-<ISSUE_ID>/before-fix.gif" \
  -f message="docs: add before-fix recording" \
  -f content="$GIF_B64" \
  -f branch="screenrecordings"
```

Extract the `download_url` from the JSON response — this is the `raw.githubusercontent.com` URL. Use it in the PR body:

```markdown
## UI before changes
![Before fix](https://raw.githubusercontent.com/<fork-owner>/<repo>/screenrecordings/screenrecordings/<workspace>-<ISSUE_ID>/before-fix.gif)

## UI after changes
![After fix](https://raw.githubusercontent.com/<fork-owner>/<repo>/screenrecordings/screenrecordings/<workspace>-<ISSUE_ID>/after-fix.gif)
```

The GIF files live on the `screenrecordings` branch of the fork only — they never appear in the PR diff and never reach upstream `main`. GitHub's camo proxy caches the rendered images permanently in the PR description, so they remain visible even if the branch is later cleaned up.

### Fallback — Manual upload

If the Contents API upload fails (permissions error, file too large):

1. Create the PR with placeholder text for the image sections.
2. Inform the user to manually drag the GIF files into the PR description on GitHub's web UI.
3. GitHub uploads them to `user-images.githubusercontent.com` and generates permanent URLs.

## Cleanup

After the PR is created and images are uploaded, remove all temporary artifacts:

```bash
rm -rf e2e-tests/_repro-artifacts/
rm -rf test-results/
```
