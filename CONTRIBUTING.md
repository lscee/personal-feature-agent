# Contributing to Personal Feature Agent

Thank you for improving Personal Feature Agent. Contributions should preserve its central workflow contract: a user approves an exact requirement before product code changes, and completion requires recorded verification evidence. This contract is an auditable coordination rule for cooperative agents, not an access-control or sandbox boundary.

## Before opening a change

For a substantial behavior change, open a GitHub issue first and describe:

- the user problem;
- the proposed workflow change;
- its effect on the approval boundary;
- new commands, permissions, network access, or data exposure;
- how the behavior will be tested in both Codex and Claude Code.

Small documentation fixes and focused test additions can go directly to a pull request.

## Development setup

Fork and clone the repository, then create a topic branch:

```bash
git checkout -b feature/short-description
```

The test suite uses Python's standard library:

```bash
python3 -m unittest discover -s tests -v
```

When Claude Code is available, validate and load the plugin locally:

```bash
claude plugin validate ./plugins/personal-feature-agent --strict
claude --plugin-dir ./plugins/personal-feature-agent
```

When Codex is available, register this repository as a local marketplace, install `personal-feature-agent@personal-feature-agent`, and exercise it from a new task.

## Design rules

- Keep `skills/feature-dev/SKILL.md`, templates, references, and scripts platform-neutral.
- Put platform-specific metadata only in the corresponding plugin or marketplace files.
- Preserve the requirement-digest approval gate. A modified requirement must require new approval.
- Derive commands from repository evidence. Do not silently add guessed shell commands.
- Treat repository-defined commands as arbitrary code; detection is not a safety verdict.
- Pass command arguments as argument vectors where possible and avoid shell interpolation, while documenting that `shell=False` does not make the invoked program safe.
- Assume command arguments, output, paths, and verification URLs can be sensitive; minimize collection and test redaction or omission where implemented.
- Never claim build, test, environment, or smoke-test success without stored evidence.
- Do not add automatic commit, push, merge, release, production deployment, or secret collection.
- Prefer Python standard-library code for runtime helpers unless an external dependency is justified.
- Keep generated state within the target repository's `.feature-agent/` directory.

## Tests

Every behavior change should include a focused test. Cover both successful and rejected paths, especially:

- invalid state transitions;
- approval digest changes;
- unsafe paths and unknown commands;
- project detection from fixture files;
- command exit status and evidence recording;
- environment verification failures;
- compatibility of both plugin manifests.

Use disposable fixture directories. Tests must not depend on production credentials, external services, or a developer's global configuration.

## Documentation

Update both `README.md` and `README.zh-CN.md` when user-facing behavior changes. Examples must be runnable or clearly marked as placeholders. Do not document a project type, command, or platform capability until it is implemented and tested.

## Pull requests

Keep pull requests focused and explain:

- what changed and why;
- how it was tested;
- any security, privacy, compatibility, or migration impact;
- whether generated artifacts or workflow states changed.

By contributing, you agree that your contribution is licensed under the Apache License 2.0.

Please follow the repository's Code of Conduct if one is added. Until then, communicate respectfully and focus review discussion on the work.
