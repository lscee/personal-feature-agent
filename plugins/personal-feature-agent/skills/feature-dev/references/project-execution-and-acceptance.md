# Project Execution and Acceptance

Use this reference after the exact requirement hash is approved and before editing product code, installing dependencies, building, testing, or starting an environment.

## Preserve the workspace

Inspect repository status before changes and retain a baseline of pre-existing modified and untracked files. All existing changes belong to the user unless proven otherwise.

- Never reset, checkout, clean, overwrite, or silently stash user work.
- Do not include unrelated files in the feature or receipt.
- If a target file already contains user changes, understand the overlap before editing. Stop when ownership or intent cannot be determined safely.
- Keep generated artifacts and command logs under `.feature-agent/` unless the project itself defines another generated location.
- Do not commit, merge, push, publish, or open an external change without a separate explicit request.

## Choose commands from evidence

Use the detector's structured command candidates and inspect each candidate's `source` before selection. Evidence priority is:

1. A command explicitly supplied by the user for this project and task.
2. Repository-scoped instructions that apply to the target path.
3. Executable project configuration: package scripts, build manifests, Make targets, task files, Docker Compose configuration, and CI steps.
4. Maintained project documentation consistent with current configuration.

Lockfiles select the package manager when they are unambiguous. Familiar ecosystem conventions may guide discovery but are not permission to execute an absent command.

If candidates conflict, inspect the relevant configuration and select only when evidence resolves the conflict. Otherwise ask the user. Pass commands as argument vectors, not interpolated shell strings. Never put requirement text, file content, secrets, or unreviewed model output into a command.

For an explicit command not represented by detection, use `--allow-unknown -- <argv...>` only after checking that it:

- came from the user or applicable repository evidence;
- is limited to the current development project;
- is not destructive or production-facing;
- does not require unapproved privilege escalation;
- does not print or transmit secrets.

An absent install, build, test, or start command is `NOT RUN`, not `PASS`. Report why it does not apply or what evidence is missing.

## Installation and implementation

Install dependencies only when required to execute the approved feature and only through an evidence-backed project-local command. Avoid global installation, broad dependency upgrades, and unrelated lockfile churn. If the approved feature needs a new dependency, justify it against existing project patterns and keep the change minimal.

Before editing, recheck the approved hash and inspect the closest analogous code and tests. Implement only the approved behavior:

- follow established architecture, naming, formatting, and public interfaces;
- preserve backward compatibility required by the approved document;
- add or update focused tests alongside behavior when the project supports them;
- avoid opportunistic refactors and unrelated defect repair;
- never weaken, delete, skip, or relabel a meaningful test to obtain a passing result.

## Build and test order

Use the narrowest useful feedback first, then run all applicable project gates affected by the change:

1. Focused static, unit, or component check for changed behavior.
2. Repository-configured formatting, lint, type, build, and test commands that cover the affected area.
3. Runtime acceptance checks mapped to the approved `AC-xxx` items.

The helper records command, source, timestamps, exit status, and log location. Treat logs as evidence, not a substitute for checking that the command covered the intended behavior. The transition to `built` validates the latest current-requirement build and test receipts whenever those phases have detected candidates; a latest failure cannot be hidden behind an older success.

## Failure loop

For every failed command or acceptance check:

1. Preserve the exact command, exit status, and relevant log path.
2. Classify the failure as approved feature code, development configuration, environment/infrastructure, missing authority/input, or unrelated pre-existing failure.
3. For code or development configuration within scope, identify evidence, make the smallest correction, and rerun the narrow failing check.
4. After a narrow check passes, rerun every broader gate affected by the correction.
5. Keep acceptance status failed until current evidence passes.

Do not enter an infinite retry loop. Stop at a real blocker when progress requires unavailable credentials or services, a user choice that changes behavior, destructive action, production access, an unknown command, external coordination, or scope outside the approved requirement. A pre-existing unrelated failure must be reported distinctly and must not be repaired under this skill.

## Start the environment

Start only a local or explicitly designated Docker development environment using an evidence-backed command. Background execution retains its PID/process-group evidence and log paths. Docker Compose candidates use detached mode. The transition to `running` binds one exact start-result digest; later verification must reuse that binding instead of selecting an unrelated service.

Derive the address from one of these sources:

- explicit project configuration;
- successful startup output;
- an inspected container port mapping;
- an explicit user-provided address.

Do not infer a conventional port or scheme. Confirm that the process/container remains healthy before verification. A PID-presence check is useful lifecycle evidence, not proof of process identity, so confirm the command and environment address as well. Record safe shutdown instructions and check the PID/process group or Compose project before acting; never terminate unrelated processes or containers.

If the application legitimately exposes no network endpoint, do not invent one. Treat the documented invocation target as the environment entry point only when the approved requirement permits it; otherwise report that a verifiable environment address is blocked.

## Acceptance evidence

Build an acceptance matrix before final verification:

| Criterion | Evidence method | Expected result | Evidence location |
| --- | --- | --- | --- |
| `AC-xxx` | exact test, request, or inspection | approved observable outcome | log, response, screenshot path, or test report |

Evidence must be current, repeatable, and tied to the running implementation. Depending on the feature, valid methods include repository tests, HTTP requests, browser automation already available to the agent, database/API inspection authorized by the project, and deterministic file or CLI output. The plugin itself must not depend on a separate UI.

Runtime self-test is successful only when:

- applicable install, build, and test gates have passed or are truthfully marked not applicable with evidence;
- the environment is running and its evidence-backed address or approved invocation target is reachable;
- every `AC-xxx` item has passed with a recorded method and evidence;
- no fatal startup error or unresolved in-scope failure remains;
- generated receipt values match the latest run and approved requirement hash.

Verifier success covers only the checks it actually performed. Add supported acceptance evidence to the receipt when the verifier cannot express a criterion; never edit generated failures into passes.

## Receipt and handoff

Keep `.feature-agent/environment.json` machine-readable and `.feature-agent/environment.md` readable without chat history. Use the environment receipt asset as the content contract. Include the approved hash, repository revision and dirty-state note, exact command sources and outcomes, environment identity/address, acceptance matrix, retries, limitations, and shutdown instructions.

The helper stores `.feature-agent/` directories and files with private POSIX modes where the filesystem supports them, rejects symbolic-link workspace escapes, redacts common secret-bearing argument flags, and removes URL query values from receipts. These are bounded safeguards, not comprehensive secret detection. Keep credentials, tokens, cookies, private keys, authorization headers, and secret environment values out of commands and URLs; inspect logs and receipts before sharing.

If verified, leave the development environment available when safe and requested, and return its address plus the receipt paths. If blocked, do not transition to `verified`; return the last valid stage, failed evidence, unmet criteria, and the minimum action required to resume.
