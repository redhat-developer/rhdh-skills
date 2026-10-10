#!/usr/bin/env node
/**
 * Bump Yarn across RHDH checkouts.
 *
 *   yarn set version <to>  → packageManager + yarnPath + binary
 *   chmod +x
 *   yarn install --mode=update-lockfile
 *   rewrite extras Yarn cannot see (ENV YARN= / Containerfile / embedded set version)
 *
 * yarn-bump.sh downloads the CLI once from repo.yarnpkg.com (same URL as
 * `yarn set version`) and passes --bin so every PR/MR commits that yarn-<to>.cjs.
 * --copy-bin remains a fallback that copies a binary already on disk.
 *
 *   bump-yarn.js --to 4.17.1 --root PATH... [--from V1,V2|--from-all] [--bin FILE|--copy-bin SRC]
 *   bump-yarn.js --scan --root PATH
 */
"use strict";

const fs = require("node:fs");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

const DEFAULT_FROM = ["4.12.0", "4.14.1"];
/** Pins --from-all must not move (legacy / dcm). */
const DENYLIST = new Set(["4.8.1", "4.9.2", "4.15.0"]);
const SKIP = new Set([
  ".git",
  "node_modules",
  ".yarn",
  "dist",
  "coverage",
  ".turbo",
]);
const YARN_BIN_RE = /^yarn-(\d{1,6}\.\d{1,6}\.\d{1,6})\.cjs$/;
const YARN_PM_RE = /^yarn@(\d{1,6}\.\d{1,6}\.\d{1,6})/;
const YARN_PATH_RE =
  /(?:^|\n)yarnPath:[^\n]*yarn-(\d{1,6}\.\d{1,6}\.\d{1,6})\.cjs/;

function cmpStr(a, b) {
  if (a < b) return -1;
  if (a > b) return 1;
  return 0;
}

function parseArgs(argv) {
  const a = {
    from: [...DEFAULT_FROM],
    fromAll: false,
    roots: [],
    to: null,
    scan: false,
    dryRun: false,
    locks: true,
    copyBin: null,
    bin: null,
  };
  for (let i = 0; i < argv.length; i += 1) {
    const x = argv[i];
    if (x === "-h" || x === "--help") {
      console.log(`Usage:
  bump-yarn.js --to VER [--from ${DEFAULT_FROM.join(",")}|--from-all] --root PATH...
               [--bin FILE|--copy-bin GH_ROOT] [--scan|--dry-run|--no-refresh-locks]

  --from-all  bump every packageManager / yarn-*.cjs pin except DENYLIST ${[...DENYLIST].join(",")}
  --bin       install that yarn-<to>.cjs into every bumped .yarn/releases (committed in the PR/MR)
  --copy-bin  copy yarn-<to>.cjs from a checkout into each --root when --bin is omitted`);
      process.exit(0);
    }
    if (x === "--scan") a.scan = true;
    else if (x === "--dry-run") a.dryRun = true;
    else if (x === "--no-refresh-locks") a.locks = false;
    else if (x === "--from-all") a.fromAll = true;
    else if (x === "--to") a.to = argv[++i];
    else if (x === "--from") {
      a.from = String(argv[++i])
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);
    } else if (x === "--root") a.roots.push(path.resolve(argv[++i]));
    else if (x === "--copy-bin") a.copyBin = path.resolve(argv[++i]);
    else if (x === "--bin") a.bin = path.resolve(argv[++i]);
    else {
      console.error(`Unknown: ${x}`);
      process.exit(1);
    }
  }
  return a;
}

function pushWalkDir(stack, full, name) {
  if (!SKIP.has(name)) {
    stack.push(full);
    return;
  }
  if (name === ".yarn") {
    const releases = path.join(full, "releases");
    if (fs.existsSync(releases)) stack.push(releases);
  }
}

function walk(root, fn) {
  const stack = [root];
  while (stack.length) {
    const dir = stack.pop();
    let ents;
    try {
      ents = fs.readdirSync(dir, { withFileTypes: true });
    } catch {
      continue;
    }
    for (const e of ents) {
      const full = path.join(dir, e.name);
      if (e.isDirectory()) pushWalkDir(stack, full, e.name);
      else if (e.isFile()) fn(full, e.name, dir);
    }
  }
}

function esc(s) {
  return s.replaceAll(/[.*+?^${}()|[\]\\]/g, (ch) => `\\${ch}`);
}

function readPm(dir) {
  try {
    const pm =
      JSON.parse(fs.readFileSync(path.join(dir, "package.json"), "utf8"))
        .packageManager || "";
    const m = YARN_PM_RE.exec(pm);
    return m ? m[1] : null;
  } catch {
    return null;
  }
}

function readYarnPath(dir) {
  try {
    const m = YARN_PATH_RE.exec(
      fs.readFileSync(path.join(dir, ".yarnrc.yml"), "utf8"),
    );
    return m ? m[1] : null;
  } catch {
    return null;
  }
}

function localBin(dir) {
  try {
    const rel = path.join(dir, ".yarn", "releases");
    const bins = fs
      .readdirSync(rel)
      .filter((n) => YARN_BIN_RE.test(n))
      .toSorted(cmpStr);
    return bins.length ? path.join(rel, bins.at(-1)) : null;
  } catch {
    return null;
  }
}

function chmodX(p) {
  try {
    fs.chmodSync(p, 0o755); // NOSONAR — intentional +x for Berry CLI binary
  } catch {
    /* ignore */
  }
}

function sh(cmd, args, cwd) {
  return spawnSync(cmd, args, {
    cwd,
    encoding: "utf8",
    env: { ...process.env, YARN_ENABLE_IMMUTABLE_INSTALLS: "false" },
    stdio: ["ignore", "pipe", "pipe"],
  });
}

function setVersion(dir, to, dryRun) {
  if (dryRun) {
    console.log(`dry-run: set version ${to} @ ${dir}`);
    return;
  }
  console.log(`yarn set version: ${dir}`);
  const bin = localBin(dir);
  const r = bin
    ? sh(process.execPath, [bin, "set", "version", to], dir)
    : sh("yarn", ["set", "version", to], dir);
  if (r.status) console.error(`warn: set version failed @ ${dir}`);
  const out = path.join(dir, ".yarn", "releases", `yarn-${to}.cjs`);
  if (fs.existsSync(out)) chmodX(out);
}

function isExtra(full, base) {
  if (base === "package.json" || base === ".yarnrc.yml") return false;
  if (
    base === "Containerfile" ||
    base === "Dockerfile" ||
    base === "run-e2e.sh"
  )
    return true;
  if (base.endsWith(".Containerfile") || base.endsWith(".Dockerfile"))
    return true;
  if (
    base === "yarn" &&
    full.includes(`${path.sep}.fullsend${path.sep}`) &&
    full.endsWith(`${path.sep}bin${path.sep}yarn`)
  ) {
    return true;
  }
  return base.endsWith(".sh") && /e2e|yarn/i.test(full);
}

const YARN_SEMVER = String.raw`\d{1,6}\.\d{1,6}\.\d{1,6}`;

function keepPin(ver, to) {
  return ver === to || DENYLIST.has(ver);
}

function rewriteExtras(text, from, to) {
  const alt = from.map(esc).join("|");
  let next = text;
  if (alt) {
    next = next.replace(
      new RegExp(String.raw`yarn-(?:${alt})\.cjs`, "g"),
      `yarn-${to}.cjs`,
    );
  }
  // Literal install pins move to --to even when that version is not in --from
  // (catalog builder.Containerfile can sit ahead of workspace pins).
  // `yarn set version $yarn_version` does not match a semver, so it stays.
  next = next.replace(
    new RegExp(String.raw`yarn set version (${YARN_SEMVER})\b`, "g"),
    (match, ver) => (keepPin(ver, to) ? match : `yarn set version ${to}`),
  );
  next = next.replace(
    new RegExp(String.raw`yarn_version=(["']?)(${YARN_SEMVER})\1`, "g"),
    (match, quote, ver) =>
      keepPin(ver, to) ? match : `yarn_version=${quote}${to}${quote}`,
  );
  return next;
}

function resolveToBin(dir, to) {
  for (let cur = dir, i = 0; i < 8; i += 1) {
    const c = path.join(cur, ".yarn", "releases", `yarn-${to}.cjs`);
    if (fs.existsSync(c)) return c;
    const parent = path.dirname(cur);
    if (parent === cur) break;
    cur = parent;
  }
  return null;
}

function collectFromVersions(root, to) {
  const versions = new Set();
  walk(root, (_full, base, dir) => {
    const bm = YARN_BIN_RE.exec(base);
    if (bm) {
      if (bm[1] !== to && !DENYLIST.has(bm[1])) versions.add(bm[1]);
      return;
    }
    if (base !== "package.json") return;
    const v = readPm(dir);
    if (v && v !== to && !DENYLIST.has(v)) versions.add(v);
  });
  return [...versions].toSorted(cmpStr);
}

function assertYarnCli(binPath) {
  const head = fs.readFileSync(binPath).subarray(0, 40).toString("utf8");
  if (!head.startsWith("#!/usr/bin/env node")) {
    throw new Error(`${binPath} is not a Yarn CLI`);
  }
}

function rewriteYarnPath(text, fromSet, to) {
  return text.replace(
    /^(yarnPath:\s*\S*yarn-)(\d{1,6}\.\d{1,6}\.\d{1,6})(\.cjs\s*)$/gm,
    (match, pre, ver, suf) =>
      fromSet.has(ver) ? `${pre}${to}${suf}` : match,
  );
}

function skipGenerated(full) {
  return full
    .split(path.sep)
    .some((part) => part === "dist-dynamic" || part === "node_modules");
}

function installReleaseBins(root, from, to, binPath, dryRun) {
  const fromSet = new Set(from);
  const payload = dryRun ? null : fs.readFileSync(binPath);
  if (!dryRun) assertYarnCli(binPath);
  const dirs = new Set();
  walk(root, (full, base, dir) => {
    if (skipGenerated(full)) return;
    const match = YARN_BIN_RE.exec(base);
    if (match && fromSet.has(match[1])) dirs.add(dir);
  });
  const installed = [];
  for (const dir of [...dirs].toSorted(cmpStr)) {
    const dest = path.join(dir, `yarn-${to}.cjs`);
    const rel = path.relative(root, dest);
    installed.push(rel);
    if (dryRun) {
      console.log(`dry-run: install ${rel}`);
      continue;
    }
    fs.writeFileSync(dest, payload);
    chmodX(dest);
    for (const name of fs.readdirSync(dir)) {
      const match = YARN_BIN_RE.exec(name);
      if (match && match[1] !== to && fromSet.has(match[1])) {
        fs.unlinkSync(path.join(dir, name));
      }
    }
    const rc = path.join(path.dirname(path.dirname(dir)), ".yarnrc.yml");
    if (!fs.existsSync(rc)) continue;
    const current = fs.readFileSync(rc, "utf8");
    const next = rewriteYarnPath(current, fromSet, to);
    if (next !== current) fs.writeFileSync(rc, next);
  }
  return installed;
}

function copyYarnBin(srcRoot, destRoot, to, dryRun) {
  const name = `yarn-${to}.cjs`;
  let src = path.join(srcRoot, ".yarn", "releases", name);
  if (!fs.existsSync(src)) src = resolveToBin(srcRoot, to);
  if (!src || !fs.existsSync(src))
    throw new Error(`no ${name} under ${srcRoot}`);
  const destDir = path.join(destRoot, ".yarn", "releases");
  const dest = path.join(destDir, name);
  if (dryRun) {
    console.log(`dry-run: copy ${src} -> ${dest}`);
    return dest;
  }
  fs.mkdirSync(destDir, { recursive: true });
  fs.copyFileSync(src, dest);
  chmodX(dest);
  for (const n of fs.readdirSync(destDir)) {
    const m = YARN_BIN_RE.exec(n);
    if (m && m[1] !== to) fs.unlinkSync(path.join(destDir, n));
  }
  return dest;
}

function bumpCount(map, key) {
  map.set(key, (map.get(key) || 0) + 1);
}

function fmtCounts(map) {
  return (
    [...map.entries()]
      .toSorted(([a], [b]) => cmpStr(a, b))
      .map(([v, n]) => `${v}×${n}`)
      .join(", ") || "(none)"
  );
}

function scan(root) {
  const releases = new Map();
  const pms = new Map();
  walk(root, (_full, base, dir) => {
    const m = YARN_BIN_RE.exec(base);
    if (m) {
      bumpCount(releases, m[1]);
      return;
    }
    if (base !== "package.json") return;
    const v = readPm(dir);
    if (v) bumpCount(pms, v);
  });
  console.log(
    `\n=== scan ${root} ===\nreleases: ${fmtCounts(releases)}\npackageManager: ${fmtCounts(pms)}`,
  );
}

function collectPmDirs(root, fromSet) {
  const pmDirs = [];
  walk(root, (_f, base, dir) => {
    if (base === "package.json" && fromSet.has(readPm(dir))) pmDirs.push(dir);
  });
  return pmDirs.toSorted(cmpStr);
}

function applyExtras(root, from, to, dryRun) {
  const extras = [];
  walk(root, (full, base) => {
    if (!isExtra(full, base)) return;
    let text;
    try {
      text = fs.readFileSync(full, "utf8");
    } catch {
      return;
    }
    if (text.length > 2e6) return;
    const next = rewriteExtras(text, from, to);
    if (next === text) return;
    const rel = path.relative(root, full);
    extras.push(rel);
    if (dryRun) console.log(`dry-run: extra ${rel}`);
    else fs.writeFileSync(full, next);
  });
  return extras;
}

function shouldSkipLock(full) {
  return full
    .split(path.sep)
    .some((p) => p === "node_modules" || p === "dist-dynamic");
}

function dropUntrackedYarnrc(dir, root) {
  const rc = path.join(dir, ".yarnrc.yml");
  if (!fs.existsSync(rc)) return;
  if (sh("git", ["ls-files", "--error-unmatch", rc], root).status === 0) return;
  try {
    fs.unlinkSync(rc);
  } catch {
    /* ignore */
  }
}

function refreshOneLock(dir, to, root) {
  const bin = resolveToBin(dir, to);
  if (!bin) {
    console.error(
      `warn: no yarn-${to}.cjs for ${dir} (bump a GH workspace first, or copy the binary into .yarn/releases/)`,
    );
    return "fail";
  }
  console.log(`locks: ${dir}`);
  const failed = Boolean(
    sh(process.execPath, [bin, "install", "--mode=update-lockfile"], dir)
      .status,
  );
  if (failed) console.error(`warn: install failed @ ${dir}`);
  dropUntrackedYarnrc(dir, root);
  return failed ? "fail" : "ok";
}

function refreshLocks(root, { fromSet, to }) {
  const stats = { ok: 0, skip: 0, fail: 0 };
  const dirs = [];
  walk(root, (full, base, dir) => {
    if (base !== "yarn.lock" || shouldSkipLock(full)) return;
    const pin = readPm(dir) || readYarnPath(dir);
    if (pin && pin !== to && !fromSet.has(pin)) {
      stats.skip += 1;
      console.log(`locks: skip ${dir} (${pin})`);
      return;
    }
    dirs.push(dir);
  });
  for (const dir of dirs.toSorted(cmpStr)) {
    stats[refreshOneLock(dir, to, root)] += 1;
  }
  return stats;
}

function bump(root, { from, to, dryRun, locks, bin }) {
  const fromSet = new Set(from);
  const bins = bin
    ? installReleaseBins(root, from, to, bin, dryRun)
    : [];
  const pmDirs = collectPmDirs(root, fromSet);
  for (const d of pmDirs) setVersion(d, to, dryRun);

  const extras = applyExtras(root, from, to, dryRun);
  const lockStats =
    locks && !dryRun ? refreshLocks(root, { fromSet, to }) : null;

  let summary = `\n=== ${root} ===\nset-version: ${pmDirs.length}  bins: ${bins.length}  extras: ${extras.length}`;
  if (bins.length) summary += `\n  ${bins.join("\n  ")}`;
  if (extras.length) summary += `\n  ${extras.join("\n  ")}`;
  if (lockStats)
    summary += `\nlocks ok/skip/fail: ${lockStats.ok}/${lockStats.skip}/${lockStats.fail}`;
  console.log(summary);
  return { pmDirs, extras, lockStats };
}

function main() {
  const args = parseArgs(process.argv.slice(2));
  if (!args.roots.length) {
    console.error("Need --root PATH");
    process.exit(1);
  }
  for (const r of args.roots) {
    if (!fs.existsSync(r)) {
      console.error(`Missing: ${r}`);
      process.exit(1);
    }
  }
  if (args.scan) {
    for (const r of args.roots) scan(r);
    return;
  }
  if (!args.to) {
    console.error("--to VERSION required (exact, not stable)");
    process.exit(1);
  }
  if (args.bin) assertYarnCli(args.bin);
  else if (args.copyBin) {
    for (const r of args.roots)
      copyYarnBin(args.copyBin, r, args.to, args.dryRun);
  }
  for (const r of args.roots) {
    if (args.fromAll) args.from = collectFromVersions(r, args.to);
    console.log(
      `to=${args.to} from=${args.from.join(",") || "(none)"} dry-run=${args.dryRun} locks=${args.locks}`,
    );
    bump(r, args);
  }
}

module.exports = {
  DENYLIST,
  DEFAULT_FROM,
  rewriteExtras,
  rewriteYarnPath,
  collectFromVersions,
  copyYarnBin,
  installReleaseBins,
  bump,
  parseArgs,
};

if (require.main === module) main();
