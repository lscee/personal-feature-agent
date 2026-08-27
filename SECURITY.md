# Security Policy

Personal Feature Agent can edit source code and execute repository-defined development commands. Treat changes to its approval gate, command selection, path handling, logging, and environment verification as security-sensitive.

The requirement-digest gate is an auditable collaboration protocol for a cooperative agent: the user reviews a requirement, approves its exact bytes, and only then does the workflow proceed to implementation. It is not a sandbox, access-control boundary, cryptographic signature, identity proof, or unforgeable authorization. SHA-256 binds the recorded approval to document content; it does not establish who approved it or make later execution safe. A malicious, compromised, misconfigured, or non-compliant agent with filesystem or tool access may bypass these helpers entirely. Enforce security boundaries independently through host permissions, sandboxing, isolation, branch protection, and human review.

## Supported versions

Security fixes are provided for the latest release on the default branch. Older releases may not receive backports.

## Reporting a vulnerability

Do not open a public issue for a suspected vulnerability.

Use the repository's **Security** tab to submit a private GitHub security advisory. Include:

- affected version or commit;
- the target operating system and agent host;
- reproduction steps using a disposable repository;
- expected and observed behavior;
- potential impact;
- a suggested remediation, if available.

Do not include real credentials, private source code, personal data, or production logs. Use minimal synthetic examples.

Maintainers will acknowledge a complete report when it is reviewed, investigate it, and coordinate disclosure and a fix when applicable. Exact response times are not guaranteed by this volunteer project.

## Security boundaries

The plugin reduces risk but is not a sandbox. Codex or Claude Code, the local shell, package managers, build tools, dependencies, containers, and model providers retain their own security properties.

Project detection is not a trust decision. A detected or documented repository command can execute arbitrary code through lifecycle hooks, build scripts, test runners, Make targets, downloaded dependencies, or the invoked executable itself. Passing arguments without shell interpolation (`shell=False`) reduces command-injection exposure, but it does not make the selected program or its inputs safe.

Execution evidence is also a data-exposure surface. `.feature-agent/runs/`, state files, and environment receipts may contain command arguments, stdout/stderr, filesystem paths, configuration data, process information, and verification URLs. Secrets embedded in arguments or URLs may also be visible in process listings or logs before this plugin records them. The plugin can reduce some accidental exposure, but it does not provide comprehensive secret detection or redaction.

Users should:

- review the requirement digest before approval;
- understand that requirement approval permits the documented workflow to continue, but does not by itself authorize privileged, destructive, networked, or production-facing actions;
- inspect repository-defined commands and dependencies as potentially arbitrary code, whether or not shell interpolation is used;
- inspect privileged, destructive, or networked commands before allowing them;
- run the workflow with least-privilege credentials;
- avoid production checkouts and production deployment targets;
- keep secrets out of prompts, command arguments, URLs, repositories, logs, and `.feature-agent/` artifacts;
- review or remove execution evidence before sharing, committing, or publishing it;
- review generated code and dependency changes before committing them.

Examples of security issues in scope include unintended approval-gate bypasses in the provided workflow, command injection, unsafe path traversal, unapproved product-code edits by the cooperative workflow, secret leakage in generated artifacts, misleading verification results, or execution of commands that were not selected from repository evidence without explicit opt-in. Reports that merely demonstrate that a fully privileged or deliberately non-compliant agent can ignore the plugin instructions are generally outside the gate's stated security boundary, although concrete defense-in-depth improvements are welcome.
