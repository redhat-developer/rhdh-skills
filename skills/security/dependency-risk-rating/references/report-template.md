# Report templates

`score.ts --format md` renders the core table and recommendation — use its
output verbatim as the heart of the report; do not recompute or restate
numbers by hand. Wrap it as follows.

## Chat report (all modes)

```
<one-sentence verdict: what changed and the overall risk>

<score.ts --format md output>

### Changelog summary
- <package>: <notes from the judgments file, one line each — only packages
  with a non-"routine" judgment or interesting notes>

### Data gaps (only if any)
Already listed by score.ts; add remediation hints if useful (e.g. "api.osv.dev
was unreachable from this environment — vulnerability data missing").
```

Keep the wrapper prose short: the verdict sentence, the changelog bullets, and
anything genuinely surprising. Do not repeat the table's contents in prose.

## PR comment (only when the user asked for it)

Same as the chat report, plus a header and a one-line footer naming the rated
head SHA, so a reader can tell whether the comment still describes the branch:

```
## Dependency update risk rating

<chat report content>

---
*Rated at <headSha>.*
```

The comment body is an external write. The wrapper prose is finalized and the
write is gated before this point — see the Reporting and Write gate sections of
`SKILL.md`. This file only describes the shape of the body. Post the approved
body with:

```bash
gh pr comment <number> --repo <owner/repo> --body-file <path>
```

Never post automatically. The user must have asked for a comment, or accepted
an offer of one, and must then approve the exact body against the head SHA.

## Mode B (single package) addendum

Append one line: "Rated without repository context — workspace, Backstage and
coverage checks were skipped."
