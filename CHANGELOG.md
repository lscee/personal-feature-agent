# Changelog

All notable changes to this project are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Fixed

- Retry transient HTTP startup failures within the configured verification timeout.

## [0.1.0] - 2026-08-26

### Added

- Cross-platform Codex and Claude Code plugin manifests.
- Approval-gated feature specification and implementation workflow.
- Portable project detection, workflow state, command recording, and verification helpers.
- Evidence-bound `built`, `running`, and `verified` transitions with forged-receipt rejection.
- Symlink-safe private workflow storage, bounded argument/URL redaction, and process-group-aware lifecycle evidence.
- Codex and Claude Code marketplace catalogs.
- Repository validation, unit tests, and Linux/macOS/Windows GitHub Actions CI.
