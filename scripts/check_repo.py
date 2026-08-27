#!/usr/bin/env python3
"""Validate the cross-platform plugin repository without third-party packages."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "personal-feature-agent"
CODEX_MANIFEST = PLUGIN / ".codex-plugin" / "plugin.json"
CLAUDE_MANIFEST = PLUGIN / ".claude-plugin" / "plugin.json"
CODEX_MARKETPLACE = ROOT / ".agents" / "plugins" / "marketplace.json"
CLAUDE_MARKETPLACE = ROOT / ".claude-plugin" / "marketplace.json"
SKILL = PLUGIN / "skills" / "feature-dev" / "SKILL.md"
SEMVER = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?$")


def load_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise AssertionError(f"missing required file: {path.relative_to(ROOT)}") from exc
    except json.JSONDecodeError as exc:
        raise AssertionError(f"invalid JSON in {path.relative_to(ROOT)}: {exc}") from exc
    if not isinstance(value, dict):
        raise AssertionError(f"expected JSON object: {path.relative_to(ROOT)}")
    return value


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def validate_manifests() -> None:
    codex = load_json(CODEX_MANIFEST)
    claude = load_json(CLAUDE_MANIFEST)
    for label, manifest in (("Codex", codex), ("Claude", claude)):
        require(manifest.get("name") == "personal-feature-agent", f"{label} plugin name is inconsistent")
        require(isinstance(manifest.get("description"), str) and manifest["description"].strip(), f"{label} description is empty")
        require(isinstance(manifest.get("version"), str) and SEMVER.fullmatch(manifest["version"]) is not None, f"{label} version is not semver")
        require(manifest.get("skills") == "./skills/", f"{label} skills must point to ./skills/")
    require(codex["version"] == claude["version"], "Codex and Claude versions differ")


def validate_marketplaces() -> None:
    for label, path in (("Codex", CODEX_MARKETPLACE), ("Claude", CLAUDE_MARKETPLACE)):
        marketplace = load_json(path)
        require(marketplace.get("name") == "personal-feature-agent", f"{label} marketplace name is inconsistent")
        plugins = marketplace.get("plugins")
        require(isinstance(plugins, list) and len(plugins) == 1, f"{label} marketplace must list exactly one plugin")
        require(plugins[0].get("name") == "personal-feature-agent", f"{label} marketplace plugin name is inconsistent")
    claude = load_json(CLAUDE_MARKETPLACE)
    require(claude["plugins"][0].get("source") == "./plugins/personal-feature-agent", "Claude marketplace source is invalid")
    codex = load_json(CODEX_MARKETPLACE)
    source = codex["plugins"][0].get("source", {})
    require(source.get("path") == "./plugins/personal-feature-agent", "Codex marketplace source is invalid")


def validate_skill() -> None:
    try:
        text = SKILL.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise AssertionError(f"missing required file: {SKILL.relative_to(ROOT)}") from exc
    require(text.startswith("---\n"), "SKILL.md must start with YAML frontmatter")
    end = text.find("\n---\n", 4)
    require(end != -1, "SKILL.md frontmatter is not closed")
    frontmatter = text[4:end]
    require(re.search(r"(?m)^name:\s*feature-dev\s*$", frontmatter) is not None, "SKILL.md name must be feature-dev")
    require(re.search(r"(?m)^description:\s*\S.+$", frontmatter) is not None, "SKILL.md description is missing")


def validate_tree() -> None:
    # Split the literals so this validator does not flag its own source.
    forbidden = ("[" + "TODO:", "YOUR_GITHUB_" + "USERNAME", "example.com" + "/plugin")
    suffixes = {".md", ".json", ".py", ".yml", ".yaml"}
    for path in ROOT.rglob("*"):
        if not path.is_file() or ".git" in path.parts or path.suffix not in suffixes:
            continue
        text = path.read_text(encoding="utf-8")
        for token in forbidden:
            require(token not in text, f"unfinished placeholder {token!r} in {path.relative_to(ROOT)}")


def main() -> int:
    checks = (validate_manifests, validate_marketplaces, validate_skill, validate_tree)
    try:
        for check in checks:
            check()
            print(f"ok: {check.__name__}")
    except AssertionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print("repository validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
