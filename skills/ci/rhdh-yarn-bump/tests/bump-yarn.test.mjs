import assert from "node:assert/strict";
import { createRequire } from "node:module";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { describe, it } from "node:test";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const scriptsDir = path.join(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
  "scripts",
);
const bumpYarn = require(path.join(scriptsDir, "bump-yarn.js"));

describe("rewriteExtras", () => {
  it("rewrites yarn binary pins and yarn set version", () => {
    const src =
      "ENV YARN=/.yarn/releases/yarn-4.17.1.cjs\nyarn set version 4.17.1\n";
    const out = bumpYarn.rewriteExtras(src, ["4.17.1"], "4.18.1");
    assert.equal(
      out,
      "ENV YARN=/.yarn/releases/yarn-4.18.1.cjs\nyarn set version 4.18.1\n",
    );
  });

  it("rewrites yarn_version and leaves the variable install line", () => {
    const src =
      'yarn_version="4.18.1" \\\nyarn set version $yarn_version; yarn -v; \\\n';
    const out = bumpYarn.rewriteExtras(src, ["4.17.1"], "4.19.0");
    assert.equal(
      out,
      'yarn_version="4.19.0" \\\nyarn set version $yarn_version; yarn -v; \\\n',
    );
  });

  it("rewrites a literal yarn set version that is not in from", () => {
    const out = bumpYarn.rewriteExtras(
      "yarn set version 4.16.0\n",
      ["4.17.1"],
      "4.19.0",
    );
    assert.equal(out, "yarn set version 4.19.0\n");
  });

  it("keeps denylist yarn_version pins and single-quoted or bare assignments", () => {
    const src =
      "yarn_version=\"4.8.1\"\nyarn_version='4.9.2'\nyarn_version=4.15.0\n";
    assert.equal(bumpYarn.rewriteExtras(src, ["4.17.1"], "4.19.0"), src);
  });

  it("keeps a yarn_version assignment that is already --to", () => {
    const src = 'yarn_version="4.19.0"\nyarn set version 4.19.0\n';
    assert.equal(bumpYarn.rewriteExtras(src, ["4.17.1"], "4.19.0"), src);
  });

  it("rewrites quoted and bare yarn_version assignments", () => {
    const src = "yarn_version='4.17.1'\nyarn_version=4.14.1\n";
    assert.equal(
      bumpYarn.rewriteExtras(src, [], "4.19.0"),
      "yarn_version='4.19.0'\nyarn_version=4.19.0\n",
    );
  });
});

describe("collectFromVersions", () => {
  it("collects packageManager pins except denylist and --to", () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), "yarn-from-"));
    fs.writeFileSync(
      path.join(root, "package.json"),
      JSON.stringify({ packageManager: "yarn@4.17.1" }),
    );
    fs.mkdirSync(path.join(root, "legacy"), { recursive: true });
    fs.writeFileSync(
      path.join(root, "legacy", "package.json"),
      JSON.stringify({ packageManager: "yarn@4.8.1" }),
    );
    fs.mkdirSync(path.join(root, ".yarn", "releases"), { recursive: true });
    fs.writeFileSync(
      path.join(root, ".yarn", "releases", "yarn-4.17.1.cjs"),
      "//",
    );
    assert.deepEqual(bumpYarn.collectFromVersions(root, "4.18.1"), ["4.17.1"]);
  });

  it("returns empty when already on --to", () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), "yarn-to-"));
    fs.writeFileSync(
      path.join(root, "package.json"),
      JSON.stringify({ packageManager: "yarn@4.18.1" }),
    );
    assert.deepEqual(bumpYarn.collectFromVersions(root, "4.18.1"), []);
  });
});

describe("copyYarnBin", () => {
  it("copies yarn-<to>.cjs and removes older binaries", () => {
    const src = fs.mkdtempSync(path.join(os.tmpdir(), "yarn-src-"));
    const dest = fs.mkdtempSync(path.join(os.tmpdir(), "yarn-dst-"));
    fs.mkdirSync(path.join(src, ".yarn", "releases"), { recursive: true });
    fs.mkdirSync(path.join(dest, ".yarn", "releases"), { recursive: true });
    fs.writeFileSync(
      path.join(src, ".yarn", "releases", "yarn-4.18.1.cjs"),
      "new",
    );
    fs.writeFileSync(
      path.join(dest, ".yarn", "releases", "yarn-4.17.1.cjs"),
      "old",
    );
    bumpYarn.copyYarnBin(src, dest, "4.18.1", false);
    assert.equal(
      fs.readFileSync(
        path.join(dest, ".yarn", "releases", "yarn-4.18.1.cjs"),
        "utf8",
      ),
      "new",
    );
    assert.equal(
      fs.existsSync(path.join(dest, ".yarn", "releases", "yarn-4.17.1.cjs")),
      false,
    );
  });
});

describe("installReleaseBins", () => {
  it("installs the fetched CLI, updates yarnPath, and keeps denylist binaries", () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), "yarn-install-"));
    const bin = path.join(root, "fetched.cjs");
    fs.writeFileSync(bin, "#!/usr/bin/env node\n/* fetched */\n");
    const rel = path.join(root, "ws", ".yarn", "releases");
    const legacy = path.join(root, "legacy", ".yarn", "releases");
    fs.mkdirSync(rel, { recursive: true });
    fs.mkdirSync(legacy, { recursive: true });
    fs.writeFileSync(path.join(rel, "yarn-4.17.1.cjs"), "old");
    fs.writeFileSync(path.join(legacy, "yarn-4.8.1.cjs"), "deny");
    fs.writeFileSync(
      path.join(root, "ws", ".yarnrc.yml"),
      "yarnPath: .yarn/releases/yarn-4.17.1.cjs\n",
    );
    fs.writeFileSync(
      path.join(root, "legacy", ".yarnrc.yml"),
      "yarnPath: .yarn/releases/yarn-4.8.1.cjs\n",
    );

    const installed = bumpYarn.installReleaseBins(
      root,
      ["4.17.1"],
      "4.19.0",
      bin,
      false,
    );
    assert.deepEqual(installed, ["ws/.yarn/releases/yarn-4.19.0.cjs"]);
    assert.equal(
      fs.readFileSync(path.join(rel, "yarn-4.19.0.cjs"), "utf8"),
      "#!/usr/bin/env node\n/* fetched */\n",
    );
    assert.equal(fs.existsSync(path.join(rel, "yarn-4.17.1.cjs")), false);
    assert.equal(
      fs.readFileSync(path.join(root, "ws", ".yarnrc.yml"), "utf8"),
      "yarnPath: .yarn/releases/yarn-4.19.0.cjs\n",
    );
    assert.equal(fs.readFileSync(path.join(legacy, "yarn-4.8.1.cjs"), "utf8"), "deny");
    assert.equal(
      fs.readFileSync(path.join(root, "legacy", ".yarnrc.yml"), "utf8"),
      "yarnPath: .yarn/releases/yarn-4.8.1.cjs\n",
    );
    const mode = fs.statSync(path.join(rel, "yarn-4.19.0.cjs")).mode & 0o777;
    assert.equal(mode, 0o755);
  });
});
