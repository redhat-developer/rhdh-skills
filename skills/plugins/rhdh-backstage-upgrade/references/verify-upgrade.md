# Verify Upgrade

Run these checks in order. Stop and fix any failures before continuing.

## Build checks

Run the scripts the checkout defines for type checking, build, lint, formatting,
and monorepo consistency. The common baseline is:

```bash
yarn tsc
yarn build
yarn lint
```

For `redhat-developer/rhdh`, use this full sequence instead of the baseline and
test command below:

```bash
yarn build
yarn test
yarn lint:check
yarn prettier:check
yarn monorepo:check
yarn build:dockerfile
```

For that checkout, include changes from `yarn build:dockerfile` in the upgrade
diff.

## Test suite

```bash
yarn test
```

If tests fail, check whether the failures are due to:

- API changes (fix per `fix-breaking-changes.md`)
- Snapshot mismatches (update snapshots: `yarn test -u`)
- Moved packages (run `versions:migrate`)

## Import validation

Check for deprecated or moved package imports:

```bash
# Packages moved to @backstage-community
grep -r '@backstage/plugin-' src/ --include='*.ts' --include='*.tsx' | grep -v node_modules | head -20
```

Cross-reference any hits against the community plugins repo to verify they haven't been moved.

## Version consistency

Verify all `@backstage/*` packages are on the same release:

```bash
cat package.json | grep '@backstage/' | sort
```

All versions should correspond to the target release and retain the dependency
range style recorded before the bump. If any are out of sync, re-run
`versions:bump`; if the range style drifted, normalize it and refresh the
lockfile.

## Runtime check (if a dev app exists)

```bash
yarn start
```

- Open the browser and verify the plugin loads
- Check the browser console for errors
- Verify core functionality works
