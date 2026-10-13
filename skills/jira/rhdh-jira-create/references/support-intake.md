# Support-case intake

How a customer support case becomes RHDH Jira work. Load this when the request
starts with a support case, a customer escalation, or an RHDHSUPP issue.

The output is the same as any other create — the input source is what differs.
Return to `workflows/create-issue.md` at Step 2 once this file has told you which
project receives what.

## The three projects

| Project | Purpose | Public? |
|---|---|---|
| RHDHSUPP | Internal engineering ↔ support conversation about a live case | No |
| RHDHBUGS | Product defects, including doc defects | **Yes** |
| RHDHPLAN | Feature requests from customers | **Yes** |

Two of the three are public. That is the whole reason the identity rules below
exist.

## Never comment on the external support case

Engineering discussion happens in **RHDHSUPP issues only**. Do not comment on a
customer's support case directly. Create an internal RHDHSUPP issue, link it to
the external case, and keep the engineering conversation there. Customer-facing
communication stays controlled by the support team.

## How a case flows

1. **Customer files** on the Customer Portal. Support confirms product, version,
   severity (1–4, 1 highest), description, trace logs, and entitlement.
2. **Support investigates** — documentation, KCS articles, reproduction attempt.
3. **Engineering engaged** — support opens an **RHDHSUPP Bug** to track the
   discussion, linked to the support ticket, with Priority, Component, and the
   issue template filled.
4. **Investigation** proceeds under SLA. Defects found along the way that are
   *unrelated* to the customer case still get their own RHDHBUGS Bug.
5. **Resolution** is a solution, a workaround, a termination (not supported, no
   further work possible, technical limitation), a product defect, or a feature
   request.
6. **Product defect** → RHDHBUGS. See below.
7. **Feature request** → RHDHPLAN. See below.
8. **Close the RHDHSUPP issue** when the investigation resolves or the customer
   goes quiet past SLA. On close, set **Story Points** to record the effort
   spent — `/rhdh-jira-authoring` carries the RHDHSUPP-specific point scale,
   which measures investigation and communication effort, not engineering size.

## Product defect: RHDHSUPP → RHDHBUGS

Create a Bug in RHDHBUGS with Priority, Component (`Documentation` for doc
defects), **Affects Version** (required at create — see `/rhdh-jira-api`), and
the Bug template filled with real reproduction steps. Link it to the customer
case through SFDC Cases Links, then comment on the RHDHSUPP issue with the
RHDHBUGS key so the customer learns when the fix lands.

```bash
# Single --from-json: versions + ADF description inside the JSON (not --description-file)
acli jira workitem create --from-json "$BUG_CREATE_JSON"

acli jira workitem link create --out RHDHSUPP-456 --in RHDHBUGS-789 --type "Related" --yes

acli jira workitem comment create --key RHDHSUPP-456 \
  --body "Defect captured in RHDHBUGS-789. Fix targeted for next y-stream release."
```

## Feature request: RHDHSUPP → RHDHPLAN

Create a `Feature Request` in RHDHPLAN with Priority, Component, the Feature
Request template, and a link to the customer case through SFDC Cases Links. Then
encourage the customer to follow up with their account team so Product Management
can prioritize it.

```bash
acli jira workitem create --project RHDHPLAN --type "Feature Request" \
  --summary "Support OIDC token refresh in admin console" \
  --description-file "$FEATURE_ADF"

acli jira workitem link create --out RHDHSUPP-456 --in RHDHPLAN-123 --type "Related" --yes
```

An accepted Feature Request is what a later Feature links back to — Step 7 of the
create workflow looks for one.

## Customer identity

Prefer the support-ticket key and a single `RHDH-Customer` label in RHDHBUGS and
RHDHPLAN. Put customer-identifying detail only in restricted-visibility comments,
and never copy a customer name into a summary, description, or any other
unprotected field on a public project. `/rhdh-jira-api` is authoritative on this.

## Fix prioritization

| Scenario | Target release | Priority |
|---|---|---|
| Default | Next y-stream (e.g. 1.11.0) | As triaged |
| Critical to the customer | Current z-stream (e.g. 1.10.4) | **Blocker** plus target fix version |
| Customer request, not urgent | Future y-stream | As triaged |

For z-stream targeting, agree it with the engineer first. If committed, set
Priority to Blocker and the target fix version.

## SLA by severity

| Severity | Response time | Notes |
|---|---|---|
| Sev 1 | 1 hour | 24x7, handed over between GEO teams |
| Sev 2 | 2 hours | 24x7 |
| Sev 3 | 4 business hours | Business hours only |
| Sev 4 | 1 business day | Business hours only |

SLA can be negotiated through the Negotiated Entitlement Process, or adjusted
once a workaround exists.

## Special case types

| Type | Handling |
|---|---|
| Strategic customer | Extra attention — an opportunity to expand the relationship |
| TAM customer | A Technical Account Manager assists with implementation |
| Consulting / Partner | Cases opened during project implementation |
| CSE customer | A Customer Success Executive helps with non-technical communication |

## Channels and ownership

`#rhdh-support` carries engineering ↔ support communication; `#rhdh-support-cases`
is the notification channel for new RHDHSUPP bugs. New-case notifications route
through Hydra, the internal notification tool. The engineering support liaison
owns the relationship with the support team — route process questions there, and
ask them for notification configuration changes.

Deeper internal references exist and require access: the RHDH Support Plan, the
RHDHSUPP CEE Process, the support dashboard and Kanban boards, RHDH CVE
Management, the troubleshooting guide, the RHDH/RHPIB/plug-in lifecycle policies,
and the severity and 24x7 qualification definitions. Do not embed their URLs in
agent output or share them externally.
