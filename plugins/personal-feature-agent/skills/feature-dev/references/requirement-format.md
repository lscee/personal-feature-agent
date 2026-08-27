# Lightweight Requirement Authoring

Use this reference only while creating, reviewing, revising, or approving `.feature-agent/requirement.md`.

## Outcome

The requirement is a small, implementation-ready agreement between the user and the coding agent. It must describe observable behavior precisely enough to implement and verify without turning a simple feature into a large product specification.

Write the whole document in the user's language unless they ask otherwise. Preserve code identifiers, commands, paths, API names, and stable IDs as written. Separate facts supported by repository evidence from assumptions and user decisions.

Do not embed the document's SHA-256 inside the document itself. The workflow state stores that binding; embedding it would change the value being approved.

## Repository investigation before the first draft

Inspect only what is needed to ground the feature:

1. User and repository-level agent instructions.
2. Current working-tree status and repository roots.
3. Manifests, lockfiles, build files, workspace configuration, and CI commands.
4. The nearest analogous feature and its tests.
5. Relevant public interfaces, data shapes, routing, persistence, and runtime configuration.
6. Documented install, build, test, and development-start commands.

Record each material observation with an `EVID-xxx` ID, source path, and implication. A convention that is not present in the repository may help locate evidence but must not be stated as a project fact.

Ask a focused question when an unresolved choice would materially change user-visible behavior, data compatibility, security, or implementation scope. Nonblocking choices may be written as explicit assumptions, but the user must be able to see them before approval.

## Required document content

Start from `../assets/requirement-template.md` and keep these concepts even when headings are adapted:

- Metadata: title, draft status, document version, and update date.
- Original request: a faithful short restatement, not invented detail.
- Repository evidence: paths and observations that constrain the solution.
- Outcome and goals: the user-visible value this feature must produce.
- Non-goals: adjacent work intentionally excluded.
- Scenarios: primary flow plus important empty, error, permission, or compatibility behavior when applicable.
- Functional requirements: atomic, observable statements with stable `FR-xxx` IDs.
- Acceptance criteria: verifiable `AC-xxx` items mapped to requirements.
- Constraints and compatibility: supported project constraints; do not create arbitrary technical mandates.
- Implementation boundary: likely affected components and preserved interfaces, grounded in evidence.
- Verification plan: how each acceptance criterion can be demonstrated.
- Assumptions and open questions: clearly distinguish resolved assumptions from approval-blocking questions.
- Revision history: concise record of meaningful document changes.

Omit an optional subsection instead of filling it with invented content. Keep the result proportional to the feature.

## Writing rules

- Give each independently editable behavior one stable `FR-xxx` ID.
- Give each independently verifiable outcome one stable `AC-xxx` ID.
- Write requirements as observable obligations, not implementation aspirations such as “should work well.”
- Include a negative or error-path criterion only when it is meaningful to the feature.
- Map every acceptance criterion to at least one requirement and every requirement to verification evidence.
- State defaults, ordering, persistence, validation, permissions, and compatibility only when relevant.
- Do not promise a command, port, URL, framework, or architectural component without repository or user evidence.
- Do not silently turn assumptions into requirements.
- Do not include unrelated cleanup, refactoring, bug repair, production rollout, merge, or release work.
- Do not include credentials, access tokens, personal data, or confidential values.

## Draft quality gate

The document can enter `awaiting_approval` only when:

- the requested feature and non-goals are unambiguous;
- every user-visible behavior has stable IDs;
- acceptance criteria are executable or objectively inspectable;
- repository facts cite source paths;
- assumptions are visible and no approval-blocking question remains;
- the verification plan covers every acceptance criterion;
- planned work remains a new feature and within local/development scope;
- the document contains no unresolved template placeholders.

## Local revision protocol

When the user asks to change one part of an unapproved document:

1. Resolve the target by stable ID or unique heading. If the target is ambiguous, ask which item they mean.
2. Read the target and only its direct dependencies: linked acceptance criteria, constraints, assumptions, verification rows, and revision history.
3. Patch only those fragments. Preserve unrelated language, IDs, ordering, and user-approved wording.
4. Add or update only the necessary IDs. Never renumber unaffected IDs.
5. Increment the document version and add a concise revision-history row.
6. Check local consistency and recalculate the current SHA-256.

Do not repeat repository discovery or regenerate the full requirement unless the requested change invalidates existing evidence, changes architecture or scope, or the user explicitly requests a full rewrite.

An approved document may be revised only before implementation begins. Use the workflow's `revise` operation to revoke the old hash first. Any changed document requires a new explicit approval. Once implementation has begun, freeze the requirement and surface new scope separately.

## Approval presentation

Before asking for approval, show:

- absolute or project-relative requirement path;
- document version;
- current SHA-256 from durable state inspection;
- unresolved assumptions, if any;
- a short summary of goals, non-goals, and acceptance coverage.

Ask the user to explicitly approve that exact SHA-256. Do not interpret silence, “looks interesting,” a revision request, or a request to inspect code as approval. Record approval only after the response and immediately verify that the current hash still matches before editing product code.
