## Dependency update risk: HIGH (100/100)

3 package(s) changed - 3 direct, 2 major, 0 minor, 1 patch, 0 added, 0 removed.

| Package | Change | Risk | Score | Why |
|---|---|---|---|---|
| tiny-evil-lib | 1.4.2 -> 2.0.0 | HIGH | 100 | major version bump (+3); published 0.2 days ago (< 3d) (+3); only 412 downloads/week (+2); adds an install script (pre/post/install) (+4); published by a different npm user than the previous version (+2); changelog: significant changes (+2) |
| @red-hat-developer-hub/plugin-utils | 1.2.0 -> 2.0.0 | LOW | 20 | major bump, but only drops EOL Node.js support (+1); published 0.7 days ago (< 3d) (+3); 3,500 downloads/week (+1); has npm provenance attestation (-1) - trusted package - capped at LOW |
| lodash | 4.17.20 -> 4.17.21 | LOW | 0 | fixes known vulnerabilities: GHSA-35jh-r3h4-6jhm (-2); changelog: bugfixes only (-1) |

**Recommendation:** Hold - do not merge without investigation: tiny-evil-lib: major version bump; published 0.2 days ago (< 3d); only 412 downloads/week. Test coverage is unknown; consider a manual smoke test.

Assessment confidence: high. Test confidence: unknown.
