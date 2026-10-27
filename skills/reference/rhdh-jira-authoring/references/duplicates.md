# Detect duplicate Jira work

Run this read-only check before creating work and during refinement audits.

## Search

1. Extract two to four meaningful phrases from the proposed or existing summary. Preserve product,
   component, error, and feature nouns; discard generic words such as add, fix, support, and issue.
2. Search every RHDH project unless the request narrows scope:

   ```jql
   project in (RHIDP, RHDHPLAN, RHDHSUPP, RHDHBUGS) AND summary ~ "KEYWORD1 KEYWORD2" AND status != Closed ORDER BY updated DESC
   ```

   The caller runs the search with whichever Jira tool it has; `/rhdh-jira-api`
   owns the search mechanics, including the silent 30-row default page that
   would make this check look clean when it is not.

3. When comparing an existing issue, add `AND key != CURRENT_KEY`.
4. Run a second search with the strongest component and one distinctive phrase when the first search
   is empty or too broad.

Report the JQL you ran and how many rows came back. Use the
authenticated host GraphQL adapter only when relationship-heavy enrichment is required and the
capability is ready. Never construct credentials or raw HTTP calls.

## Rank candidates

Score title phrase overlap first, then shared component, parent or hierarchy proximity, issue type,
and current status. Treat exact product names and error signatures as stronger than generic nouns.

Classify each candidate:

- **Likely duplicate**: same intended outcome and affected area.
- **Related**: overlapping context but a distinct outcome.
- **Not duplicate**: superficial wording only.

## Result

Return the candidate key, summary, status, relationship, confidence, and one-sentence rationale.
Before creation, stop for a likely duplicate and ask whether to update the existing work or continue
with an explicitly distinct scope. During an audit, report findings only — linking or closing an
issue is a separate write that needs its own approval.
