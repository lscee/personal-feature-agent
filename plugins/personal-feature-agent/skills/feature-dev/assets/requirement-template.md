# Feature Requirement: <feature name>

| Field | Value |
| --- | --- |
| Status | Draft |
| Document version | 1 |
| Updated | <YYYY-MM-DD> |
| Requirement owner | User |

> Keep the SHA-256 outside this document. Approval binding belongs in `.feature-agent/state.json`.

## Original request

<Faithful, concise restatement of the user's request.>

## Repository evidence

| ID | Source | Observation | Requirement implication |
| --- | --- | --- | --- |
| EVID-001 | `<repository/path>` | <Observed fact> | <How this constrains the feature> |

## Desired outcome

<What the user will be able to do or observe when the feature is complete.>

## Goals

- GOAL-001: <Required outcome>

## Non-goals

- NON-GOAL-001: <Adjacent behavior intentionally excluded>

## User scenarios

### SCN-001 — <Primary scenario>

- Given <starting condition>
- When <user or system action>
- Then <observable result>

## Functional requirements

- FR-001: <Atomic, observable behavior>
- FR-002: <Validation, empty state, or error behavior when applicable>

## Acceptance criteria

| ID | Requirement | Verifiable outcome |
| --- | --- | --- |
| AC-001 | FR-001 | Given <condition>, when <action>, then <observable result>. |
| AC-002 | FR-002 | Given <condition>, when <action>, then <observable result>. |

## Constraints and compatibility

- CON-001: <Constraint supported by user direction or repository evidence>

## Implementation boundary

### Expected affected areas

- `<repository/path-or-component>` — <why it is likely affected>

### Interfaces and behavior to preserve

- <Existing interface, data, or behavior that must remain compatible>

## Verification plan

| Acceptance criterion | Planned method | Evidence to retain |
| --- | --- | --- |
| AC-001 | <Test, request, browser check, CLI check, or inspection> | <Log, response, report, or artifact> |
| AC-002 | <Method> | <Evidence> |

## Assumptions

- ASM-001: <Visible, nonblocking assumption>

## Open questions

- None.

## Revision history

| Version | Date | Change | Requested by |
| --- | --- | --- | --- |
| 1 | <YYYY-MM-DD> | Initial draft | User |
