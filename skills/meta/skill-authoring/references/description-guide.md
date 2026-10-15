# Description Optimization Guide

Full guide: <https://agentskills.io/skill-creation/optimizing-descriptions>

## How Triggering Works

Agents load only `name` + `description` at startup. When a user's task matches a description, the agent reads the full SKILL.md into context.

Key insight: agents only consult skills for tasks they can't easily handle on their own. Simple one-step queries may not trigger a skill even if the description matches — the agent handles them directly. Complex, multi-step, or specialized queries reliably trigger when the description matches.

## Writing Effective Descriptions

Leading-word and pruning vocabulary: `skill-quality.md` only — do not restate those essays here.

### Structure

1. First sentence: what the skill does
2. Second sentence: "Use when [specific triggers]"
3. Additional sentences: cover edge phrasings, related terms, near-miss scenarios

### Be Pushy

Agents tend to undertrigger. Make descriptions slightly aggressive about when to activate:

**Too passive:**

```
Helps with dashboard creation.
```

**Better:**

```
Build fast dashboards to display internal data. Use when the user mentions
dashboards, data visualization, internal metrics, or wants to display any
kind of data, even if they don't explicitly ask for a "dashboard."
```

### Constraints

- Max 1024 characters
- Must be non-empty
- Write in third person

## Optimization Process

These queries evaluate routing only. Put them in the prompt-mode routing dataset
described by `evaluation-guide.md`; explicitly invoking the skill cannot prove
that an agent would have selected it. Task behavior belongs in a separate
skill-mode evaluation.

### Step 1: Design eval queries

Write two sets:

**Should-trigger (8-10 queries):**

- Different phrasings of the same intent
- Formal and casual variants
- Cases where user doesn't name the skill explicitly but clearly needs it
- Uncommon use cases
- Cases where this skill competes with another but should win

**Should-not-trigger (8-10 queries):**

- Near-misses that share keywords but need different capabilities
- Adjacent tasks that belong to other skills
- Queries that use the same terms in different contexts

### Step 2: Evaluate

For each query, ask: would the agent correctly decide to load/not-load this skill based on the description alone?

### Step 3: Revise

- Should-trigger queries failing → description is too narrow. Broaden scope.
- Should-not-trigger queries firing → description is too broad. Add specificity.
- Avoid adding specific keywords from failed queries — that's overfitting. Find the general category.
- If stuck after several iterations, try a structurally different description rather than incremental tweaks.

### Step 4: Validate

Write a fresh holdout set of queries never used during optimization. Prefer enough to cover each branch and near-miss (same bar as Step 1). These tell you whether your changes generalize.

### Step 5: Final check

- Under 1024 characters?
- Covers the main use cases?
- Excludes adjacent-but-different tasks?
- Would a new user's natural phrasing match?
