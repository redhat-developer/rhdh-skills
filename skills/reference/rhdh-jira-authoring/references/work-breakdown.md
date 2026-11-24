# Work breakdown

Use when splitting a Feature into Epics or an Epic into Stories and Tasks.

## Start from what is settled

Carry forward the source outcomes, constraints, exclusions, and customer or
documentation considerations. Put implementation and test decisions that affect
delivery in the issue text. Keep supporting context in the review notes. Adapt
the RHDH templates to the team's conventions. Ask only about gaps that change
the work.

## Slice by delivery outcome

Prefer small, independently verifiable outcomes. A Story that lets a user import
an OCI entity and see it in the catalog covers one outcome across the API, UI,
and tests. Propose a Spike when a material unknown prevents slicing. For wide
mechanical refactors, use explicit expand, migrate, and contract stages when
appropriate.

Use the team's hierarchy, ticket types, and ownership. Epics often follow team
delivery boundaries. Include engineering tests with the work they cover. Add
separate QE or documentation issues when they represent distinct work the team
wants to track. Propose ownership for confirmation rather than copying the
parent's team or assignee automatically.

State each slice's outcome and observable acceptance criteria. Record real
blockers and flag overlapping work, including existing issues that could cover
a proposed slice. Show what is deferred or unresolved so the reviewer can see
where the source scope went.
