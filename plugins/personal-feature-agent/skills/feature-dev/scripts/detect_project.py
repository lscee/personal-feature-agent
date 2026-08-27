#!/usr/bin/env python3
"""Detect project tooling and print evidence-backed command candidates as JSON.

No command is executed. Candidates are emitted only when a corresponding
manifest, lockfile, configured script, source marker, or Make target exists.
"""

from __future__ import annotations

import argparse
import configparser
import json
import os
import re
import shlex
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple


SCHEMA_VERSION = 1
PHASES = ("install", "build", "test", "start")
SHELL_META = frozenset({"|", "||", "&", "&&", ";", ">", ">>", "<", "<<"})
PYTHON_EXECUTABLE = "python" if os.name == "nt" else "python3"
SHELL_COMMAND_FLAGS = {
    "sh": frozenset({"-c"}),
    "bash": frozenset({"-c"}),
    "dash": frozenset({"-c"}),
    "fish": frozenset({"-c"}),
    "ksh": frozenset({"-c"}),
    "zsh": frozenset({"-c"}),
    "cmd": frozenset({"/c", "/k"}),
    "cmd.exe": frozenset({"/c", "/k"}),
    "powershell": frozenset({"-c", "-command", "-encodedcommand"}),
    "powershell.exe": frozenset({"-c", "-command", "-encodedcommand"}),
    "pwsh": frozenset({"-c", "-command", "-encodedcommand"}),
    "pwsh.exe": frozenset({"-c", "-command", "-encodedcommand"}),
}


def _candidate(
    project_type: str,
    argv: Sequence[str],
    source: str,
    description: str,
    cwd: str = ".",
) -> Dict[str, Any]:
    return {
        "argv": list(argv),
        "cwd": cwd,
        "project_type": project_type,
        "source": source,
        "description": description,
    }


def _read_text(path: Path, warnings: List[str]) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        warnings.append(f"cannot read {path.name}: {exc}")
        return None


def _read_json(path: Path, warnings: List[str]) -> Optional[Dict[str, Any]]:
    text = _read_text(path, warnings)
    if text is None:
        return None
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        warnings.append(f"invalid JSON in {path.name}: {exc}")
        return None
    if not isinstance(value, dict):
        warnings.append(f"expected a JSON object in {path.name}")
        return None
    return value


def _manager_from_package_json(package: Dict[str, Any]) -> Optional[str]:
    value = package.get("packageManager")
    if not isinstance(value, str):
        return None
    name = value.split("@", 1)[0].strip().lower()
    return name if name in {"npm", "pnpm", "yarn", "bun"} else None


def _node_manager(root: Path, package: Dict[str, Any], warnings: List[str]) -> str:
    declared = _manager_from_package_json(package)
    if declared:
        return declared
    locks = [
        ("pnpm", "pnpm-lock.yaml"),
        ("yarn", "yarn.lock"),
        ("npm", "package-lock.json"),
        ("npm", "npm-shrinkwrap.json"),
        ("bun", "bun.lockb"),
        ("bun", "bun.lock"),
    ]
    present = [(manager, name) for manager, name in locks if (root / name).is_file()]
    if len({manager for manager, _ in present}) > 1:
        warnings.append(
            "multiple Node package-manager lockfiles found; script candidates use the first "
            "supported lockfile unless package.json declares packageManager"
        )
    return present[0][0] if present else "npm"


def _node_script_argv(manager: str, script: str) -> List[str]:
    return [manager, "run", script]


def _detect_node(
    root: Path,
    detections: List[Dict[str, Any]],
    commands: Dict[str, List[Dict[str, Any]]],
    warnings: List[str],
) -> None:
    manifest = root / "package.json"
    if not manifest.is_file():
        return
    evidence = ["package.json"]
    for name in (
        "package-lock.json",
        "npm-shrinkwrap.json",
        "pnpm-lock.yaml",
        "yarn.lock",
        "bun.lockb",
        "bun.lock",
    ):
        if (root / name).is_file():
            evidence.append(name)
    detections.append({"type": "node", "evidence": evidence})
    package = _read_json(manifest, warnings)
    if package is None:
        return
    manager = _node_manager(root, package, warnings)

    if (root / "package-lock.json").is_file():
        commands["install"].append(
            _candidate("node", ["npm", "ci"], "package-lock.json", "Install locked npm dependencies")
        )
    if (root / "npm-shrinkwrap.json").is_file():
        commands["install"].append(
            _candidate("node", ["npm", "ci"], "npm-shrinkwrap.json", "Install locked npm dependencies")
        )
    if (root / "pnpm-lock.yaml").is_file():
        commands["install"].append(
            _candidate(
                "node",
                ["pnpm", "install", "--frozen-lockfile"],
                "pnpm-lock.yaml",
                "Install locked pnpm dependencies",
            )
        )
    if (root / "yarn.lock").is_file():
        yarn_args = ["yarn", "install", "--frozen-lockfile"]
        package_manager = package.get("packageManager")
        if (root / ".yarnrc.yml").is_file() or (
            isinstance(package_manager, str)
            and re.match(r"^yarn@(?:[2-9]|[1-9][0-9])(?:\.|$)", package_manager)
        ):
            yarn_args = ["yarn", "install", "--immutable"]
        commands["install"].append(
            _candidate("node", yarn_args, "yarn.lock", "Install locked Yarn dependencies")
        )
    for bun_lock in ("bun.lock", "bun.lockb"):
        if (root / bun_lock).is_file():
            commands["install"].append(
                _candidate(
                    "node",
                    ["bun", "install", "--frozen-lockfile"],
                    bun_lock,
                    "Install locked Bun dependencies",
                )
            )

    scripts = package.get("scripts")
    if not isinstance(scripts, dict):
        return
    phase_scripts = {
        "build": ("build",),
        "test": ("test",),
        "start": ("start", "dev", "serve", "preview"),
    }
    for phase, names in phase_scripts.items():
        for name in names:
            value = scripts.get(name)
            if isinstance(value, str) and value.strip():
                commands[phase].append(
                    _candidate(
                        "node",
                        _node_script_argv(manager, name),
                        f"package.json:scripts.{name}",
                        f"Run configured Node script '{name}'",
                    )
                )


def _pyproject_sections(path: Path, warnings: List[str]) -> Set[str]:
    text = _read_text(path, warnings)
    if text is None:
        return set()
    return {
        match.group(1).strip()
        for match in re.finditer(r"(?m)^\s*\[([^\]]+)\]\s*(?:#.*)?$", text)
    }


def _setup_cfg_has_pytest(path: Path, warnings: List[str]) -> bool:
    parser = configparser.ConfigParser()
    try:
        parser.read(path, encoding="utf-8")
    except (OSError, configparser.Error) as exc:
        warnings.append(f"cannot parse setup.cfg: {exc}")
        return False
    return parser.has_section("tool:pytest")


def _safe_command_line(value: str) -> Optional[List[str]]:
    try:
        argv = shlex.split(value, posix=os.name != "nt")
    except ValueError:
        return None
    if os.name == "nt":
        argv = [
            token[1:-1]
            if len(token) >= 2 and token[0] == token[-1] and token[0] in {"'", '"'}
            else token
            for token in argv
        ]
    if not argv or any(token in SHELL_META for token in argv):
        return None
    for index, token in enumerate(argv[:-1]):
        executable = token.replace("\\", "/").rsplit("/", 1)[-1].lower()
        unsafe_flags = SHELL_COMMAND_FLAGS.get(executable)
        if unsafe_flags and argv[index + 1].lower() in unsafe_flags:
            # A Procfile is repository evidence, but an embedded shell command
            # still defeats argv-level inspection. It can be used only through
            # the explicit, user-reviewed unknown-command path.
            return None
    if argv:
        executable = argv[0].replace("\\", "/").rsplit("/", 1)[-1].lower()
        unsafe_flags = SHELL_COMMAND_FLAGS.get(executable)
        if unsafe_flags and any(item.lower() in unsafe_flags for item in argv[1:]):
            return None
    if any("\x00" in token for token in argv):
        return None
    return argv


def _detect_python(
    root: Path,
    detections: List[Dict[str, Any]],
    commands: Dict[str, List[Dict[str, Any]]],
    warnings: List[str],
) -> None:
    evidence_names = (
        "pyproject.toml",
        "setup.py",
        "setup.cfg",
        "requirements.txt",
        "Pipfile",
        "Pipfile.lock",
        "poetry.lock",
        "uv.lock",
        "pytest.ini",
        "tox.ini",
        "manage.py",
        "Procfile",
    )
    evidence = [name for name in evidence_names if (root / name).is_file()]
    requirements = sorted(
        path.name for path in root.glob("requirements*.txt") if path.is_file()
    )
    for name in requirements:
        if name not in evidence:
            evidence.append(name)
    if not evidence:
        return
    detections.append({"type": "python", "evidence": evidence})

    if (root / "uv.lock").is_file():
        commands["install"].append(
            _candidate("python", ["uv", "sync", "--frozen"], "uv.lock", "Sync locked uv environment")
        )
    if (root / "poetry.lock").is_file() and (root / "pyproject.toml").is_file():
        commands["install"].append(
            _candidate(
                "python",
                ["poetry", "install", "--sync"],
                "poetry.lock",
                "Install locked Poetry dependencies",
            )
        )
    if (root / "Pipfile.lock").is_file():
        commands["install"].append(
            _candidate("python", ["pipenv", "sync"], "Pipfile.lock", "Install locked Pipenv dependencies")
        )
    for name in requirements:
        commands["install"].append(
            _candidate(
                "python",
                [PYTHON_EXECUTABLE, "-m", "pip", "install", "-r", name],
                name,
                f"Install dependencies declared by {name}",
            )
        )
    if not requirements and (
        (root / "pyproject.toml").is_file()
        or (root / "setup.py").is_file()
        or (root / "setup.cfg").is_file()
    ):
        source = next(
            name
            for name in ("pyproject.toml", "setup.py", "setup.cfg")
            if (root / name).is_file()
        )
        commands["install"].append(
            _candidate(
                "python",
                [PYTHON_EXECUTABLE, "-m", "pip", "install", "."],
                source,
                "Install the local Python project",
            )
        )

    sections: Set[str] = set()
    if (root / "pyproject.toml").is_file():
        sections = _pyproject_sections(root / "pyproject.toml", warnings)
        if "build-system" in sections:
            commands["build"].append(
                _candidate(
                    "python",
                    [PYTHON_EXECUTABLE, "-m", "build"],
                    "pyproject.toml:[build-system]",
                    "Build the configured Python package",
                )
            )

    pytest_source: Optional[str] = None
    if (root / "pytest.ini").is_file():
        pytest_source = "pytest.ini"
    elif "tool.pytest.ini_options" in sections:
        pytest_source = "pyproject.toml:[tool.pytest.ini_options]"
    elif (root / "setup.cfg").is_file() and _setup_cfg_has_pytest(root / "setup.cfg", warnings):
        pytest_source = "setup.cfg:[tool:pytest]"
    if pytest_source:
        commands["test"].append(
            _candidate(
                "python",
                [PYTHON_EXECUTABLE, "-m", "pytest"],
                pytest_source,
                "Run configured pytest suite",
            )
        )
    if (root / "tox.ini").is_file():
        commands["test"].append(
            _candidate("python", ["tox"], "tox.ini", "Run configured tox environments")
        )
    if (root / "manage.py").is_file():
        commands["test"].append(
            _candidate(
                "python",
                [PYTHON_EXECUTABLE, "manage.py", "test"],
                "manage.py",
                "Run Django project tests",
            )
        )
        manage_text = _read_text(root / "manage.py", warnings) or ""
        if "execute_from_command_line" in manage_text:
            commands["start"].append(
                _candidate(
                    "python",
                    [PYTHON_EXECUTABLE, "manage.py", "runserver"],
                    "manage.py:execute_from_command_line",
                    "Start the configured Django development server",
                )
            )
    if (root / "Procfile").is_file():
        procfile = _read_text(root / "Procfile", warnings)
        if procfile is not None:
            for number, line in enumerate(procfile.splitlines(), 1):
                match = re.match(r"^\s*web\s*:\s*(.+?)\s*$", line)
                if not match:
                    continue
                argv = _safe_command_line(match.group(1))
                if argv:
                    commands["start"].append(
                        _candidate(
                            "python",
                            argv,
                            f"Procfile:{number}",
                            "Start the explicitly configured web process",
                        )
                    )
                else:
                    warnings.append(
                        f"skipped Procfile:{number} because it requires shell parsing or is invalid"
                    )


def _detect_rust(
    root: Path,
    detections: List[Dict[str, Any]],
    commands: Dict[str, List[Dict[str, Any]]],
    warnings: List[str],
) -> None:
    del warnings
    if not (root / "Cargo.toml").is_file():
        return
    evidence = ["Cargo.toml"]
    locked = (root / "Cargo.lock").is_file()
    if locked:
        evidence.append("Cargo.lock")
    detections.append({"type": "rust", "evidence": evidence})
    suffix = ["--locked"] if locked else []
    if locked:
        commands["install"].append(
            _candidate("rust", ["cargo", "fetch", "--locked"], "Cargo.lock", "Fetch locked Cargo dependencies")
        )
    commands["build"].append(
        _candidate("rust", ["cargo", "build", *suffix], "Cargo.toml", "Build Cargo targets")
    )
    commands["test"].append(
        _candidate("rust", ["cargo", "test", *suffix], "Cargo.toml", "Run Cargo tests")
    )
    cargo_text = (root / "Cargo.toml").read_text(encoding="utf-8", errors="replace")
    has_binary = (root / "src" / "main.rs").is_file() or "[[bin]]" in cargo_text
    if has_binary:
        commands["start"].append(
            _candidate("rust", ["cargo", "run", *suffix], "Cargo.toml", "Run configured Cargo binary")
        )


def _go_root_is_main(root: Path) -> bool:
    package_pattern = re.compile(r"(?m)^\s*package\s+main\s*(?://.*)?$")
    for path in root.glob("*.go"):
        if path.name.endswith("_test.go") or not path.is_file():
            continue
        try:
            if package_pattern.search(path.read_text(encoding="utf-8")):
                return True
        except (OSError, UnicodeDecodeError):
            continue
    return False


def _detect_go(
    root: Path,
    detections: List[Dict[str, Any]],
    commands: Dict[str, List[Dict[str, Any]]],
    warnings: List[str],
) -> None:
    del warnings
    if not (root / "go.mod").is_file():
        return
    evidence = ["go.mod"]
    if (root / "go.sum").is_file():
        evidence.append("go.sum")
    detections.append({"type": "go", "evidence": evidence})
    commands["install"].append(
        _candidate("go", ["go", "mod", "download"], "go.mod", "Download declared Go modules")
    )
    commands["build"].append(
        _candidate("go", ["go", "build", "./..."], "go.mod", "Build all Go packages")
    )
    commands["test"].append(
        _candidate("go", ["go", "test", "./..."], "go.mod", "Test all Go packages")
    )
    if _go_root_is_main(root):
        commands["start"].append(
            _candidate("go", ["go", "run", "."], "go.mod + root package main", "Run root Go main package")
        )


def _detect_java(
    root: Path,
    detections: List[Dict[str, Any]],
    commands: Dict[str, List[Dict[str, Any]]],
    warnings: List[str],
) -> None:
    evidence: List[str] = []
    if (root / "pom.xml").is_file():
        evidence.append("pom.xml")
    gradle_manifests = [
        name
        for name in ("build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts")
        if (root / name).is_file()
    ]
    evidence.extend(gradle_manifests)
    if not evidence:
        return
    detections.append({"type": "java", "evidence": evidence})

    if (root / "pom.xml").is_file():
        if os.name == "nt" and (root / "mvnw.cmd").is_file():
            mvn = "mvnw.cmd"
        else:
            mvn = "./mvnw" if (root / "mvnw").is_file() else "mvn"
        pom_text = _read_text(root / "pom.xml", warnings) or ""
        commands["build"].append(
            _candidate("java", [mvn, "package"], "pom.xml", "Build Maven project")
        )
        commands["test"].append(
            _candidate("java", [mvn, "test"], "pom.xml", "Run Maven tests")
        )
        if "spring-boot-maven-plugin" in pom_text:
            commands["start"].append(
                _candidate(
                    "java",
                    [mvn, "spring-boot:run"],
                    "pom.xml:spring-boot-maven-plugin",
                    "Start configured Spring Boot application",
                )
            )

    if gradle_manifests:
        if os.name == "nt" and (root / "gradlew.bat").is_file():
            gradle = "gradlew.bat"
        else:
            gradle = "./gradlew" if (root / "gradlew").is_file() else "gradle"
        source = gradle_manifests[0]
        build_text = "\n".join(
            _read_text(root / name, warnings) or "" for name in gradle_manifests
        )
        commands["build"].append(
            _candidate("java", [gradle, "build"], source, "Build Gradle project")
        )
        commands["test"].append(
            _candidate("java", [gradle, "test"], source, "Run Gradle tests")
        )
        if re.search(r"(?:id\s*\(?\s*['\"]application['\"]|apply\s+plugin:\s*['\"]application['\"])", build_text):
            commands["start"].append(
                _candidate("java", [gradle, "run"], f"{source}:application plugin", "Run Gradle application")
            )
        if "org.springframework.boot" in build_text:
            commands["start"].append(
                _candidate(
                    "java",
                    [gradle, "bootRun"],
                    f"{source}:org.springframework.boot",
                    "Start configured Spring Boot application",
                )
            )


def _make_targets(path: Path, warnings: List[str]) -> Set[str]:
    text = _read_text(path, warnings)
    if text is None:
        return set()
    targets: Set[str] = set()
    for line in text.splitlines():
        if not line or line[0].isspace() or line.startswith("#"):
            continue
        match = re.match(r"^([A-Za-z0-9][A-Za-z0-9_.-]*(?:\s+[A-Za-z0-9][A-Za-z0-9_.-]*)*)\s*:(?![=])", line)
        if match:
            targets.update(match.group(1).split())
    targets.discard(".PHONY")
    return targets


def _detect_make(
    root: Path,
    detections: List[Dict[str, Any]],
    commands: Dict[str, List[Dict[str, Any]]],
    warnings: List[str],
) -> None:
    makefile = next((root / name for name in ("Makefile", "makefile", "GNUmakefile") if (root / name).is_file()), None)
    if makefile is None:
        return
    targets = _make_targets(makefile, warnings)
    detections.append({"type": "make", "evidence": [makefile.name], "targets": sorted(targets)})
    aliases = {
        "install": ("install", "setup", "bootstrap", "deps", "dependencies"),
        "build": ("build", "all", "compile", "package"),
        "test": ("test", "tests", "check", "verify"),
        "start": ("start", "run", "serve", "dev", "up"),
    }
    for phase, names in aliases.items():
        for name in names:
            if name in targets:
                commands[phase].append(
                    _candidate(
                        "make",
                        ["make", "-f", makefile.name, name],
                        f"{makefile.name}:target:{name}",
                        f"Run configured Make target '{name}'",
                    )
                )


def _detect_docker(
    root: Path,
    detections: List[Dict[str, Any]],
    commands: Dict[str, List[Dict[str, Any]]],
    warnings: List[str],
) -> None:
    del warnings
    compose_files = [
        name
        for name in ("compose.yaml", "compose.yml", "docker-compose.yaml", "docker-compose.yml")
        if (root / name).is_file()
    ]
    dockerfiles = sorted(path.name for path in root.glob("Dockerfile*") if path.is_file())
    evidence = [*compose_files, *dockerfiles]
    if not evidence:
        return
    detections.append({"type": "docker", "evidence": evidence})
    for name in compose_files:
        prefix = ["docker", "compose", "-f", name]
        commands["build"].append(
            _candidate("docker", [*prefix, "build"], name, "Build configured Compose services")
        )
        commands["start"].append(
            _candidate(
                "docker",
                [*prefix, "up", "--detach"],
                name,
                "Start configured Compose services in detached development mode",
            )
        )
    for name in dockerfiles:
        commands["build"].append(
            _candidate(
                "docker",
                ["docker", "build", "-f", name, "."],
                name,
                f"Build image from {name}",
            )
        )


def _deduplicate(commands: Dict[str, List[Dict[str, Any]]]) -> None:
    for phase in PHASES:
        unique: List[Dict[str, Any]] = []
        seen: Set[Tuple[Tuple[str, ...], str]] = set()
        for item in commands[phase]:
            key = (tuple(item["argv"]), item["cwd"])
            if key not in seen:
                seen.add(key)
                unique.append(item)
        commands[phase] = unique


def detect_project(root: Path) -> Dict[str, Any]:
    root = root.expanduser().resolve()
    if not root.exists() or not root.is_dir():
        raise ValueError(f"project root is not a directory: {root}")
    detections: List[Dict[str, Any]] = []
    commands: Dict[str, List[Dict[str, Any]]] = {phase: [] for phase in PHASES}
    warnings: List[str] = []
    detectors = (
        _detect_node,
        _detect_python,
        _detect_rust,
        _detect_go,
        _detect_java,
        _detect_make,
        _detect_docker,
    )
    for detector in detectors:
        detector(root, detections, commands, warnings)
    _deduplicate(commands)
    return {
        "schema_version": SCHEMA_VERSION,
        "project_root": str(root),
        "detected_types": detections,
        "commands": commands,
        "warnings": warnings,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="target project root (default: current directory)")
    parser.add_argument("--compact", action="store_true", help="print compact JSON")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = detect_project(Path(args.root))
    except ValueError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
        return 2
    print(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=None if args.compact else 2,
            sort_keys=True,
            separators=(",", ":") if args.compact else None,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
