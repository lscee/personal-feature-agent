# Development Environment Verification Receipt

| Field | Value |
| --- | --- |
| Status | `VERIFIED` or `BLOCKED` |
| Feature | <feature name> |
| Generated | <ISO-8601 timestamp with timezone> |
| Project root | `<absolute project root>` |
| Requirement | `.feature-agent/requirement.md` |
| Approved requirement SHA-256 | `<sha256>` |
| Repository revision | `<commit or unavailable with reason>` |
| Working-tree note | <clean, or concise pre-existing/new-change distinction> |

## Implemented scope

<Concise description of what changed within the approved requirement.>

### Changed files

| Path | Purpose |
| --- | --- |
| `<repository/path>` | <feature-related change> |

## Command results

| Phase | Exact command or candidate | Evidence source | Result | Exit | Log/evidence |
| --- | --- | --- | --- | ---: | --- |
| Install | <command, `NOT RUN`, or `NOT APPLICABLE`> | <config/doc/user source> | <result and reason> | <code or `N/A`> | `<path or N/A>` |
| Build | <command, `NOT RUN`, or `NOT APPLICABLE`> | <source> | <result and reason> | <code or `N/A`> | `<path or N/A>` |
| Test | <command, `NOT RUN`, or `NOT APPLICABLE`> | <source> | <result and reason> | <code or `N/A`> | `<path or N/A>` |
| Start | <command> | <source> | <result> | <code or running> | `<path>` |

## Environment

| Field | Value |
| --- | --- |
| Mode | Local process or Docker |
| Address / entry point | `<evidence-backed URL or approved invocation target>` |
| Address evidence | <configuration, startup log, container mapping, or user input> |
| Process / container | `<PID, container ID/name, or N/A>` |
| Bound start run | `<run id, result path, and result SHA-256>` |
| Started | <ISO-8601 timestamp with timezone> |
| Health | <check performed and current result> |
| Access notes | <safe instructions; no secrets> |
| Shutdown | `<evidence-backed shutdown command or instructions>` |

## Acceptance results

| Criterion | Method | Expected | Actual | Result | Evidence |
| --- | --- | --- | --- | --- | --- |
| AC-001 | <exact check> | <approved outcome> | <observed outcome> | `PASS`, `FAIL`, or `NOT RUN` | `<path, response summary, or report>` |

## Agent self-test

<What the agent exercised against the running implementation and what it observed.>

## Failure and retry history

| Attempt | Failure evidence | Bounded correction | Rerun result |
| ---: | --- | --- | --- |
| 1 | <log/check or `None`> | <change or `None`> | <result> |

## Known limitations and deviations

- <Remaining limitation, approved deviation, or `None known`>

## Blocker details

<For `BLOCKED`, state the last valid workflow stage, exact failure, unmet acceptance criteria, attempted corrections, and minimum action needed. For `VERIFIED`, write `None`.>

## Reproduce verification

1. <Evidence-backed environment access or start step>
2. <Exact acceptance check>
3. <Expected observable result>

> A blank value is not a passing result. Use `NOT RUN`, `NOT APPLICABLE`, or `BLOCKED` with an explanation whenever evidence is unavailable.
