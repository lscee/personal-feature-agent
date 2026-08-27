#!/usr/bin/env python3
"""Execute and audit an explicit install/build/test/start command safely.

Commands are launched without a shell. By default, a command must exactly
match an evidence-backed candidate from detect_project.py. Use --allow-unknown
only after a human has explicitly approved a project-specific command.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

try:
    from .detect_project import PHASES, detect_project
except ImportError:  # Executed as a standalone script.
    from detect_project import PHASES, detect_project

try:
    from .state import (
        STATES,
        StateError,
        assert_requirement_unchanged,
        ensure_private_workspace_directory,
        load_state,
        private_atomic_write,
        private_open_binary_append,
        private_touch,
    )
except ImportError:  # Executed as a standalone script.
    from state import (
        STATES,
        StateError,
        assert_requirement_unchanged,
        ensure_private_workspace_directory,
        load_state,
        private_atomic_write,
        private_open_binary_append,
        private_touch,
    )


SCHEMA_VERSION = 1
AGENT_DIR = ".feature-agent"
RUNS_DIR = "runs"


class RunnerError(RuntimeError):
    """A command selection, policy, or execution setup error."""


MINIMUM_STATE = {
    "install": "implementing",
    "build": "implementing",
    "test": "implementing",
    "start": "built",
}
SENSITIVE_ARGUMENT_NAME = re.compile(
    r"(?:^|[-_])(token|password|passwd|secret|api[-_]?key|authorization|credential)(?:$|[-_])",
    re.IGNORECASE,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _write_json(root: Path, path: Path, data: Dict[str, Any]) -> None:
    try:
        private_atomic_write(
            root,
            path,
            json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        )
    except StateError as exc:
        raise RunnerError(f"unsafe feature-agent audit path: {exc}") from exc


def _write_text(root: Path, path: Path, content: str) -> None:
    try:
        private_atomic_write(root, path, content)
    except StateError as exc:
        raise RunnerError(f"unsafe feature-agent log path: {exc}") from exc


def _touch(root: Path, path: Path) -> None:
    try:
        private_touch(root, path)
    except (OSError, StateError) as exc:
        raise RunnerError(f"unsafe feature-agent log path: {exc}") from exc


def _open_log(root: Path, path: Path) -> Any:
    try:
        return private_open_binary_append(root, path)
    except (OSError, StateError) as exc:
        raise RunnerError(f"unsafe feature-agent log path: {exc}") from exc


def _safe_cwd(root: Path, relative: str) -> Path:
    cwd = (root / relative).resolve()
    try:
        cwd.relative_to(root)
    except ValueError as exc:
        raise RunnerError(f"command working directory escapes project root: {relative}") from exc
    if not cwd.is_dir():
        raise RunnerError(f"command working directory is not a directory: {cwd}")
    return cwd


def _validate_argv(argv: Sequence[str]) -> List[str]:
    result = list(argv)
    if not result:
        raise RunnerError("no command was provided; choose --candidate or provide argv after --")
    if any(not isinstance(item, str) or not item or "\x00" in item for item in result):
        raise RunnerError("command argv contains an empty or invalid value")
    return result


def _redact_argv(argv: Sequence[str]) -> Tuple[List[str], bool]:
    """Redact common secret-bearing arguments before durable audit logging."""
    redacted: List[str] = []
    hide_next = False
    changed = False
    for item in argv:
        if hide_next:
            redacted.append("<redacted>")
            hide_next = False
            changed = True
            continue
        if "=" in item:
            name, value = item.split("=", 1)
            normalized = name.lstrip("-")
            if SENSITIVE_ARGUMENT_NAME.search(normalized):
                redacted.append(f"{name}=<redacted>")
                changed = changed or value != "<redacted>"
                continue
        normalized = item.lstrip("-")
        if item.startswith("-") and SENSITIVE_ARGUMENT_NAME.search(normalized):
            redacted.append(item)
            hide_next = True
            continue
        redacted.append(item)
    return redacted, changed


def _process_group_options() -> Dict[str, Any]:
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def _terminate_process_tree(process: subprocess.Popen[Any]) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        else:
            os.killpg(process.pid, signal.SIGKILL)
    except (OSError, subprocess.SubprocessError):
        pass
    if process.poll() is None:
        try:
            process.kill()
        except OSError:
            pass


def command_candidates(root: Path, phase: str) -> List[Dict[str, Any]]:
    if phase not in PHASES:
        raise RunnerError(f"unknown phase {phase!r}")
    return detect_project(root)["commands"][phase]


def select_command(
    root: Path,
    phase: str,
    candidate_index: Optional[int],
    explicit_argv: Sequence[str],
    allow_unknown: bool,
) -> Tuple[List[str], str, str, bool, Optional[int]]:
    candidates = command_candidates(root, phase)
    explicit = list(explicit_argv)
    if explicit and explicit[0] == "--":
        explicit = explicit[1:]
    if candidate_index is not None and explicit:
        raise RunnerError("choose either --candidate or explicit argv, not both")
    if candidate_index is not None:
        if candidate_index < 0 or candidate_index >= len(candidates):
            raise RunnerError(
                f"candidate index {candidate_index} is out of range for {phase}; "
                f"available candidates: 0..{len(candidates) - 1}"
            )
        item = candidates[candidate_index]
        return (
            _validate_argv(item["argv"]),
            item.get("cwd", "."),
            item.get("source", "detected candidate"),
            True,
            candidate_index,
        )
    argv = _validate_argv(explicit)
    for index, item in enumerate(candidates):
        if argv == item.get("argv") and item.get("cwd", ".") == ".":
            return argv, ".", item.get("source", "detected candidate"), True, index
    if not allow_unknown:
        raise RunnerError(
            "refusing command because it is not an exact detected candidate; "
            "inspect detect_project.py output or pass --allow-unknown after explicit approval"
        )
    return argv, ".", "explicitly approved unknown command", False, None


def _new_run_directory(root: Path, phase: str) -> Tuple[str, Path]:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    run_id = f"{timestamp}-{phase}-{os.urandom(4).hex()}"
    try:
        path = ensure_private_workspace_directory(root, RUNS_DIR, run_id, exist_ok=False)
        return run_id, path
    except StateError as exc:
        raise RunnerError(f"unsafe feature-agent runs directory: {exc}") from exc


def assert_phase_allowed(root: Path, phase: str) -> Dict[str, Any]:
    minimum = MINIMUM_STATE.get(phase)
    if minimum is None:
        raise RunnerError(f"unknown phase {phase!r}")
    try:
        data = load_state(root)
        current_index = STATES.index(data["state"])
        minimum_index = STATES.index(minimum)
        if current_index < minimum_index:
            raise RunnerError(
                f"phase {phase!r} requires workflow state {minimum!r} or later; "
                f"current state is {data['state']!r}"
            )
        assert_requirement_unchanged(root, data)
        return data
    except StateError as exc:
        raise RunnerError(f"workflow gate rejected {phase!r}: {exc}") from exc


def execute_command(
    root: Path,
    phase: str,
    argv: Sequence[str],
    *,
    cwd: str = ".",
    source: str = "explicit command",
    known_candidate: bool = False,
    unknown_approved: bool = False,
    candidate_index: Optional[int] = None,
    timeout: Optional[float] = None,
    background: bool = False,
    startup_wait: float = 1.0,
) -> Dict[str, Any]:
    root = root.expanduser().resolve()
    if not root.is_dir():
        raise RunnerError(f"project root is not a directory: {root}")
    if phase not in PHASES:
        raise RunnerError(f"unknown phase {phase!r}")
    if background and phase != "start":
        raise RunnerError("--background is only allowed for the start phase")
    if timeout is not None and timeout <= 0:
        raise RunnerError("timeout must be greater than zero")
    if startup_wait < 0 or startup_wait > 30:
        raise RunnerError("startup wait must be between 0 and 30 seconds")
    if not known_candidate and not unknown_approved:
        raise RunnerError(
            "refusing unknown command; it must be selected from detected candidates or be "
            "explicitly approved with --allow-unknown"
        )
    workflow = assert_phase_allowed(root, phase)
    command = _validate_argv(argv)
    execution_cwd = _safe_cwd(root, cwd)
    run_id, run_dir = _new_run_directory(root, phase)
    stdout_path = run_dir / "stdout.log"
    stderr_path = run_dir / "stderr.log"
    command_path = run_dir / "command.json"
    result_path = run_dir / "result.json"
    started_at = utc_now()
    started = time.monotonic()
    audit_command, argv_redacted = _redact_argv(command)
    metadata: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "phase": phase,
        "argv": audit_command,
        "argv_redacted": argv_redacted,
        "cwd": str(execution_cwd.relative_to(root)) or ".",
        "source": source,
        "known_candidate": known_candidate,
        "unknown_command_explicitly_approved": unknown_approved,
        "candidate_index": candidate_index,
        "background": background,
        "started_at": started_at,
        "workflow_state": workflow["state"],
        "approved_requirement_sha256": (workflow.get("requirement") or {}).get("sha256"),
    }
    _write_json(root, command_path, metadata)

    status = "failed"
    exit_code: Optional[int] = None
    pid: Optional[int] = None
    process_group_id: Optional[int] = None
    error: Optional[str] = None
    if background:
        try:
            with _open_log(root, stdout_path) as stdout_handle, _open_log(
                root, stderr_path
            ) as stderr_handle:
                process = subprocess.Popen(
                    command,
                    cwd=execution_cwd,
                    stdin=subprocess.DEVNULL,
                    stdout=stdout_handle,
                    stderr=stderr_handle,
                    shell=False,
                    **_process_group_options(),
                )
                pid = process.pid
                process_group_id = process.pid if os.name != "nt" else None
                try:
                    exit_code = process.wait(timeout=startup_wait)
                    status = "completed" if exit_code == 0 else "failed"
                except subprocess.TimeoutExpired:
                    status = "running"
                    # This CLI deliberately hands ownership of the detached service to
                    # the caller. Mark the local Popen handle as released so its
                    # destructor does not warn or attempt to manage that live service.
                    process.returncode = 0
        except OSError as exc:
            _touch(root, stdout_path)
            _write_text(root, stderr_path, f"{exc}\n")
            exit_code = 127
            error = str(exc)
            status = "failed"
    else:
        try:
            process = subprocess.Popen(
                command,
                cwd=execution_cwd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                shell=False,
                **_process_group_options(),
            )
            pid = process.pid
            process_group_id = process.pid if os.name != "nt" else None
            try:
                stdout, stderr = process.communicate(timeout=timeout)
                exit_code = process.returncode
                status = "completed" if exit_code == 0 else "failed"
            except subprocess.TimeoutExpired as exc:
                _terminate_process_tree(process)
                stdout_after, stderr_after = process.communicate()
                stdout_before = exc.stdout or ""
                stderr_before = exc.stderr or ""
                if isinstance(stdout_before, bytes):
                    stdout_before = stdout_before.decode("utf-8", errors="replace")
                if isinstance(stderr_before, bytes):
                    stderr_before = stderr_before.decode("utf-8", errors="replace")
                stdout = stdout_before + stdout_after
                stderr = stderr_before + stderr_after
                exit_code = 124
                status = "timed_out"
                error = f"command exceeded timeout of {timeout} seconds"
            _write_text(root, stdout_path, stdout)
            _write_text(root, stderr_path, stderr)
        except OSError as exc:
            _touch(root, stdout_path)
            _write_text(root, stderr_path, f"{exc}\n")
            exit_code = 127
            error = str(exc)
            status = "failed"

    duration = round(time.monotonic() - started, 3)
    result: Dict[str, Any] = {
        **metadata,
        "status": status,
        "exit_code": exit_code,
        "pid": pid,
        "process_group_id": process_group_id,
        "duration_seconds": duration,
        "finished_at": None if status == "running" else utc_now(),
        "error": error,
        "run_directory": str(run_dir.relative_to(root)),
        "stdout_path": str(stdout_path.relative_to(root)),
        "stderr_path": str(stderr_path.relative_to(root)),
        "result_path": str(result_path.relative_to(root)),
    }
    _write_json(root, result_path, result)
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog="Explicit command example: run_command.py --root . build -- npm run build",
    )
    parser.add_argument("--root", default=".", help="target project root (default: current directory)")
    parser.add_argument("phase", choices=PHASES)
    parser.add_argument("--candidate", type=int, help="zero-based candidate index from detect_project.py")
    parser.add_argument(
        "--allow-unknown",
        action="store_true",
        help="permit an explicit command not present in detected candidates",
    )
    parser.add_argument("--timeout", type=float, help="foreground timeout in seconds")
    parser.add_argument(
        "--background",
        action="store_true",
        help="start a service in the background (start phase only)",
    )
    parser.add_argument(
        "--startup-wait",
        type=float,
        default=1.0,
        help="seconds to wait for immediate background failure (default: 1)",
    )
    return parser


def _process_exit_code(result: Dict[str, Any]) -> int:
    if result["status"] in {"completed", "running"} and result["exit_code"] in {0, None}:
        return 0
    code = result.get("exit_code")
    return code if isinstance(code, int) and 1 <= code <= 125 else 1


def main(argv: Optional[Sequence[str]] = None) -> int:
    raw_argv = list(argv) if argv is not None else sys.argv[1:]
    command: List[str] = []
    if "--" in raw_argv:
        delimiter = raw_argv.index("--")
        command = raw_argv[delimiter + 1 :]
        raw_argv = raw_argv[:delimiter]
    args = _parser().parse_args(raw_argv)
    try:
        root = Path(args.root).expanduser().resolve()
        if not root.is_dir():
            raise RunnerError(f"project root is not a directory: {root}")
        command, cwd, source, known, candidate_index = select_command(
            root, args.phase, args.candidate, command, args.allow_unknown
        )
        result = execute_command(
            root,
            args.phase,
            command,
            cwd=cwd,
            source=source,
            known_candidate=known,
            unknown_approved=args.allow_unknown and not known,
            candidate_index=candidate_index,
            timeout=args.timeout,
            background=args.background,
            startup_wait=args.startup_wait,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return _process_exit_code(result)
    except (RunnerError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
