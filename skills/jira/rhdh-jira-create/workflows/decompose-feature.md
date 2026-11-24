# Break down a Feature or Epic

## Draft

Read the source scope and relevant existing work through `/rhdh-jira-api`.
Use `/rhdh-jira-authoring` for slicing, issue text, and duplicate checks. Start
with direct children unless the user requests more depth. Propose reusing
existing issues by key where they cover a slice.

Keep one editable Markdown draft with the hierarchy, proposed issue text,
fields, and dependencies. Carry settled answers forward and flag any unchecked
sources or unresolved decisions. When preparing to create, invoke `/grilling`
once for material gaps across the batch.

## Review and create

Follow the team's acceptance criteria conventions. When it uses the dedicated
field, ask `/rhdh-jira-api` to resolve it and prepare its value separately from
the description. Invoke `/prose-editing` once on the issue text in the
**flavored** register, then show the whole draft, including each issue's parent,
project, type, team, Security Level, and acceptance criteria.

Before publishing, confirm the parent and finish duplicate checks. Use
`/rhdh-jira-api` to prepare the create and link payloads and apply its required
field, visibility, and customer identity rules. Group exact operations with
known targets for `/mutation-gate`. If dependent writes need new Jira keys,
present those operations for approval once Jira returns the keys.

Read back each new issue to verify fields and relationships. Stop on failure and
report the partial results. If a create outcome is uncertain, verify that the
issue does not exist before retrying. Route edits to reused issues through
`/rhdh-jira-update`.
