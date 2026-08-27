# Personal Feature Agent

[简体中文](README.zh-CN.md)

Personal Feature Agent is a Codex and Claude Code plugin that turns a small feature idea into a reviewed requirement, working code, and a verified development environment inside an existing repository.

It adds a deliberate workflow boundary between planning and coding: the agent may inspect the repository and revise the requirement, but the documented workflow does not permit product-code changes until you approve the exact SHA-256 digest of the current requirement document. This is an auditable collaboration rule for a cooperative agent, not a security boundary.

## What it does

```text
feature idea
    -> inspect repository evidence
    -> draft .feature-agent/requirement.md
    -> revise only the requested sections
    -> approve the exact requirement digest
    -> implement the feature
    -> build and test with repository-defined commands
    -> start a local or Docker development environment
    -> run an agent smoke test
    -> return an environment receipt
```

The workflow is designed for a person shipping a focused new feature. It keeps the specification lightweight, makes approval auditable, and records execution evidence in the target project rather than relying on chat history alone.

## What it does not do

- It is not a bug-fixing, incident-response, or production-deployment agent.
- It does not replace product discovery, architecture review, security review, or human QA.
- It does not write to Jira or require Jenkins, a hosted service, or a dedicated UI.
- It does not automatically commit, push, merge, publish, or deploy to production.
- It does not invent build commands or report success without recorded evidence.

## Approval gate

The requirement has a content digest. Approval is valid only for the exact digest shown by the agent. Editing the requirement after approval changes its digest and invalidates that approval.

This gate preserves the product workflow—review the requirement first, then develop only the approved scope—and leaves an auditable record of what was approved. It is not a sandbox, access-control mechanism, cryptographic signature, proof of user identity, or authorization token. SHA-256 identifies the document bytes; it does not make an operation safe or grant authority. A malicious, compromised, misconfigured, or non-compliant agent that already has filesystem or tool access could bypass the helpers and edit code directly. Use host permissions, sandboxing, isolated checkouts, branch protection, code review, and other independently enforced controls when you need a security boundary.

Before approval, the workflow may:

- read the repository;
- detect project commands from existing files;
- create or revise `.feature-agent/requirement.md`;
- explain scope, acceptance criteria, assumptions, and risks.

Only after approval may the workflow edit product code, install dependencies, build, test, or start the environment. Potentially destructive, privileged, networked, or production-facing actions remain subject to the host agent's own permission controls and the user's instructions; the digest gate does not approve those actions by itself.

## Supported repositories

The bundled detector recognizes evidence for:

- Node.js projects;
- Python projects;
- Rust projects;
- Go projects;
- Java projects using Maven or Gradle;
- Make-based projects;
- Docker and Docker Compose projects.

Detection is evidence-driven. Commands are proposed only when supported by files already present in the target repository, such as package manifests, lockfiles, build files, or container configuration. A repository can also supply explicit commands through its documentation and agent instructions. Detection means only that the command is associated with repository evidence; it does not mean the command or repository is trusted or safe. Build scripts, package hooks, Make targets, test runners, and executables can run arbitrary code even when the helper invokes them with `shell=False` and an argument vector. Having a recognized manifest also does not guarantee that the local machine has the required runtime, credentials, services, or dependencies.

## Installation

Prerequisites:

- Codex or Claude Code;
- Python 3.10 or newer for the bundled deterministic helpers;
- Git;
- the toolchain required by the project you want to modify;
- Docker only when that project uses Docker for its development environment.

### Codex

Register the GitHub repository as a marketplace, then install the plugin:

```bash
codex plugin marketplace add lscee/personal-feature-agent
codex plugin add personal-feature-agent@personal-feature-agent
```

Start a new Codex task after installation so the new skill is discovered.

### Claude Code

For normal installation from GitHub:

```bash
claude plugin marketplace add lscee/personal-feature-agent
claude plugin install personal-feature-agent@personal-feature-agent
```

For local development, clone the repository and load the plugin directory without installing it:

```bash
git clone https://github.com/lscee/personal-feature-agent.git
cd personal-feature-agent
claude --plugin-dir "$PWD/plugins/personal-feature-agent"
```

On Windows, use `python` when Python is not exposed as `python3`.

## Using the agent

Work from the repository in which the feature should be implemented. Ask Codex to use the `feature-dev` skill, or invoke the Claude Code plugin skill as `/personal-feature-agent:feature-dev`.

Example request:

```text
Use feature-dev to add a JSON health endpoint that reports the application
version and service status. Draft the requirement first. Do not implement it
until I approve the exact requirement digest.
```

The agent inspects the repository and writes `.feature-agent/requirement.md`. Review it and request focused edits normally:

```text
In the acceptance criteria, change the endpoint from /health to /api/health.
Keep every other section unchanged.
```

When the document is correct, approve the exact digest reported by the agent:

```text
I approve requirement SHA-256 <digest-reported-by-the-agent>. Continue.
```

The agent then implements the approved scope, runs the detected build and test commands, starts the development environment when possible, performs a smoke test, and writes an environment receipt. If the environment cannot be started or verified, it reports the failure and evidence instead of claiming completion.

## Generated artifacts

The target repository receives a local `.feature-agent/` workspace:

```text
.feature-agent/
├── requirement.md          # reviewed feature specification
├── state.json              # workflow state and approved digest
├── environment.json        # machine-readable verification result
├── environment.md          # human-readable handoff
└── runs/                   # command output and execution evidence
```

These artifacts intentionally live beside the code so a resumed session can reconstruct the workflow state. The helpers reject symbolic links in this workspace and, on filesystems with meaningful POSIX mode bits, create directories as `0700` and evidence files as `0600`. Add `.feature-agent/` to the target repository's ignore rules if the evidence should remain local, or commit selected documents if they are useful to the team. Treat the whole directory as potentially sensitive: command arguments, stdout/stderr, local paths, environment details, and verification URLs may be recorded. Common secret-bearing flags and URL query values are redacted from structured evidence, but arbitrary logs cannot be reliably scrubbed. Avoid putting credentials in prompts, command-line arguments, or URLs, and inspect every artifact before sharing or committing it.

## Runtime helpers

Most users should let the skill orchestrate these helpers. Maintainers and advanced users can inspect the state directly:

```bash
python3 plugins/personal-feature-agent/skills/feature-dev/scripts/state.py \
  --root /path/to/target-project show

python3 plugins/personal-feature-agent/skills/feature-dev/scripts/detect_project.py \
  --root /path/to/target-project
```

The runtime also includes command execution and environment verification helpers with workflow checks. Unknown commands are rejected by default; explicit opt-in is required before running a command that was not derived from repository evidence. Entering `built` rechecks current build/test records, entering `running` binds an exact successful start result, and entering `verified` rechecks that result plus traceable HTTP or test evidence. Minimal hand-written success receipts are rejected. These checks reduce accidental misuse by a cooperative agent, but they do not turn repository-defined commands into safe commands or prevent a capable agent from using other available tools.

## Repository layout

```text
.
├── .agents/plugins/marketplace.json       # Codex marketplace
├── .claude-plugin/marketplace.json         # Claude Code marketplace
├── plugins/personal-feature-agent/
│   ├── .codex-plugin/plugin.json
│   ├── .claude-plugin/plugin.json
│   └── skills/feature-dev/
│       ├── SKILL.md
│       ├── assets/
│       ├── references/
│       └── scripts/
└── tests/
```

The workflow instructions, templates, and deterministic scripts are shared. Only the platform manifests and installation paths differ, which keeps Codex and Claude Code behavior aligned without maintaining two independent agents.

## Local validation

Run repository validation and the test suite from the repository root:

```bash
make check
```

Without `make`, run `python3 scripts/check_repo.py` followed by `python3 -m unittest discover -s tests -v`.

Build the standalone release archive with `make package`; the ZIP is written under `dist/`.

Validate the Claude Code plugin manifest and loading behavior when Claude Code is installed:

```bash
claude plugin validate ./plugins/personal-feature-agent --strict
claude --plugin-dir ./plugins/personal-feature-agent
```

For Codex, add the local marketplace and start a fresh task using the installed plugin. Exercise the workflow against a disposable fixture repository; do not use a production checkout for plugin development.

## Privacy and security

The plugin itself contains no Jira, Jenkins, telemetry, analytics, or external service integration. It operates through the coding agent and local tools available in the current environment. Your Codex or Claude Code configuration, model provider, shell commands, package managers, and project dependencies may still use network services or process repository content under their own terms.

- Review the requirement and digest before approval.
- Never place secrets in feature prompts or committed `.feature-agent/` artifacts.
- Use least-privilege credentials and a disposable development environment.
- Treat every repository-defined install, build, test, and start command as arbitrary code, and inspect it before execution; `shell=False` prevents shell interpolation but does not make the invoked program safe.
- Assume logs, command arguments, and verification URLs may contain sensitive information; avoid secrets in arguments and URLs, and review `.feature-agent/` before sharing it.
- Inspect proposed commands before allowing privileged, destructive, or networked operations.
- Keep production credentials and production deployment targets out of this workflow.
- Review all generated code and evidence before committing or publishing it.

See [SECURITY.md](SECURITY.md) for vulnerability reporting.

## Contributing

Contributions are welcome. Please read [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request. Useful contributions include additional detector fixtures, safer execution rules, clearer requirement templates, cross-platform tests, and documentation improvements.

## License

Licensed under the [Apache License 2.0](LICENSE).
