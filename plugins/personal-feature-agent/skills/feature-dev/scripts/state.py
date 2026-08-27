#!/usr/bin/env python3
"""Manage the deterministic feature delivery state stored in a target project.

This module intentionally uses only the Python standard library so the same
workflow can be driven by Codex, Claude Code, or a human operator.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

try:
    from .detect_project import detect_project
except ImportError:  # Executed as a standalone script.
    from detect_project import detect_project


SCHEMA_VERSION = 1
STATES: Tuple[str, ...] = (
    "draft",
    "awaiting_approval",
    "approved",
    "implementing",
    "built",
    "running",
    "verified",
)
NEXT_STATE = {current: following for current, following in zip(STATES, STATES[1:])}
APPROVED_STATES = frozenset(STATES[STATES.index("approved") :])
AGENT_DIR = ".feature-agent"
STATE_FILE = "state.json"
DEFAULT_REQUIREMENT = f"{AGENT_DIR}/requirement.md"
ENVIRONMENT_RECEIPT = f"{AGENT_DIR}/environment.json"
RUNS_DIR = "runs"
PRIVATE_DIRECTORY_MODE = 0o700
PRIVATE_FILE_MODE = 0o600


class StateError(RuntimeError):
    """A user-correctable state or approval integrity error."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def project_root(path: Union[str, os.PathLike[str]]) -> Path:
    root = Path(path).expanduser().resolve()
    if not root.exists():
        raise StateError(f"project root does not exist: {root}")
    if not root.is_dir():
        raise StateError(f"project root is not a directory: {root}")
    return root


def _best_effort_chmod(path: Path, mode: int) -> None:
    """Tighten local permissions where POSIX mode bits are meaningful."""
    if os.name == "nt":
        return
    try:
        os.chmod(path, mode)
    except OSError:
        # Some mounted filesystems do not implement chmod. The path and
        # symlink checks remain mandatory even when mode bits are unavailable.
        pass


def _secure_path_inside_root(root: Path, candidate: Path) -> Path:
    """Return a lexical path after rejecting traversal and existing symlinks."""
    canonical_root = project_root(root)
    lexical = candidate.expanduser()
    if not lexical.is_absolute():
        lexical = canonical_root / lexical
    try:
        relative = lexical.relative_to(canonical_root)
    except ValueError as exc:
        raise StateError(f"workspace path is outside the project root: {lexical}") from exc
    if ".." in relative.parts:
        raise StateError(f"workspace path contains parent traversal: {lexical}")

    current = canonical_root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise StateError(f"workspace path must not contain symbolic links: {current}")

    resolved = lexical.resolve(strict=False)
    try:
        resolved.relative_to(canonical_root)
    except ValueError as exc:
        raise StateError(f"workspace path resolves outside the project root: {lexical}") from exc
    return lexical


def secure_workspace_path(root: Path, *parts: str) -> Path:
    """Resolve a path beneath .feature-agent without following any symlink."""
    relative = Path(*parts) if parts else Path()
    if relative.is_absolute() or ".." in relative.parts:
        raise StateError("feature-agent workspace paths must be relative and cannot contain '..'")
    canonical_root = project_root(root)
    return _secure_path_inside_root(canonical_root, canonical_root / AGENT_DIR / relative)


def ensure_private_workspace_directory(
    root: Path,
    *parts: str,
    exist_ok: bool = True,
) -> Path:
    """Create a private directory tree inside .feature-agent without symlink traversal."""
    canonical_root = project_root(root)
    target = secure_workspace_path(canonical_root, *parts)
    agent_relative = target.relative_to(canonical_root)
    current = canonical_root
    for index, part in enumerate(agent_relative.parts):
        current = current / part
        is_target = index == len(agent_relative.parts) - 1
        if current.is_symlink():
            raise StateError(f"workspace directory must not be a symbolic link: {current}")
        if current.exists():
            if not current.is_dir():
                raise StateError(f"workspace directory path is not a directory: {current}")
            if is_target and not exist_ok:
                raise StateError(f"workspace directory already exists: {current}")
        else:
            try:
                current.mkdir(mode=PRIVATE_DIRECTORY_MODE)
            except FileExistsError:
                if current.is_symlink() or not current.is_dir():
                    raise StateError(f"unsafe workspace directory appeared: {current}")
                if is_target and not exist_ok:
                    raise StateError(f"workspace directory already exists: {current}")
        if current.is_symlink():
            raise StateError(f"workspace directory must not be a symbolic link: {current}")
        _best_effort_chmod(current, PRIVATE_DIRECTORY_MODE)

    # Recheck the completed chain after creation to catch path replacement.
    return secure_workspace_path(canonical_root, *parts)


def _workspace_relative_parts(root: Path, path: Path) -> Tuple[str, ...]:
    canonical_root = project_root(root)
    secure = _secure_path_inside_root(canonical_root, path)
    try:
        relative = secure.relative_to(canonical_root / AGENT_DIR)
    except ValueError as exc:
        raise StateError(f"write target must be inside {AGENT_DIR}: {secure}") from exc
    return tuple(relative.parts)


def private_atomic_write(root: Path, path: Path, content: Union[str, bytes]) -> None:
    """Atomically replace a private workspace file with mode 0600 where supported."""
    canonical_root = project_root(root)
    relative_parts = _workspace_relative_parts(canonical_root, path)
    target = secure_workspace_path(canonical_root, *relative_parts)
    parent_parts = relative_parts[:-1]
    ensure_private_workspace_directory(canonical_root, *parent_parts)
    target = secure_workspace_path(canonical_root, *relative_parts)
    if target.exists() and not target.is_file():
        raise StateError(f"workspace file target is not a regular file: {target}")

    temporary_name = f".{target.name}.{uuid.uuid4().hex}.tmp"
    temporary = secure_workspace_path(canonical_root, *parent_parts, temporary_name)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor: Optional[int] = None
    try:
        descriptor = os.open(temporary, flags, PRIVATE_FILE_MODE)
        if os.name != "nt":
            try:
                os.fchmod(descriptor, PRIVATE_FILE_MODE)
            except OSError:
                pass
        mode = "wb" if isinstance(content, bytes) else "w"
        kwargs: Dict[str, Any] = {}
        if mode == "w":
            kwargs = {"encoding": "utf-8", "newline": "\n"}
        with os.fdopen(descriptor, mode, **kwargs) as handle:
            descriptor = None
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        secure_workspace_path(canonical_root, *parent_parts)
        secure_workspace_path(canonical_root, *relative_parts)
        os.replace(temporary, target)
        _best_effort_chmod(target, PRIVATE_FILE_MODE)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def private_open_binary_append(root: Path, path: Path) -> Any:
    """Open a private regular workspace file for binary append without following symlinks."""
    canonical_root = project_root(root)
    relative_parts = _workspace_relative_parts(canonical_root, path)
    ensure_private_workspace_directory(canonical_root, *relative_parts[:-1])
    target = secure_workspace_path(canonical_root, *relative_parts)
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(target, flags, PRIVATE_FILE_MODE)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise StateError(f"workspace log target is not a regular file: {target}")
        if os.name != "nt":
            try:
                os.fchmod(descriptor, PRIVATE_FILE_MODE)
            except OSError:
                pass
        return os.fdopen(descriptor, "ab", buffering=0)
    except BaseException:
        os.close(descriptor)
        raise


def private_touch(root: Path, path: Path) -> None:
    with private_open_binary_append(root, path):
        pass


def state_path(root: Path) -> Path:
    return secure_workspace_path(root, STATE_FILE)


def _atomic_json_write(root: Path, path: Path, data: Dict[str, Any]) -> None:
    private_atomic_write(
        root,
        path,
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )


def _validate_state_document(data: Any, path: Path) -> Dict[str, Any]:
    if not isinstance(data, dict):
        raise StateError(f"invalid state document (expected object): {path}")
    if data.get("schema_version") != SCHEMA_VERSION:
        raise StateError(
            f"unsupported state schema {data.get('schema_version')!r}; expected {SCHEMA_VERSION}"
        )
    current = data.get("state")
    if current not in STATES:
        raise StateError(f"invalid workflow state {current!r} in {path}")
    if not isinstance(data.get("history"), list):
        raise StateError(f"invalid state history in {path}")
    return data


def load_state(root: Path) -> Dict[str, Any]:
    path = state_path(root)
    if not path.is_file():
        raise StateError(f"workflow is not initialized; run 'state.py --root {root} init'")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StateError(f"cannot read state file {path}: {exc}") from exc
    validated = _validate_state_document(data, path)
    if validated.get("project_root") != str(root):
        raise StateError(
            "workflow state belongs to a different project root; initialize and approve "
            "the feature again in this checkout"
        )
    return validated


def init_state(root: Path) -> Tuple[Dict[str, Any], bool]:
    path = state_path(root)
    if path.exists():
        return load_state(root), False
    timestamp = utc_now()
    data: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "project_root": str(root),
        "state": "draft",
        "created_at": timestamp,
        "updated_at": timestamp,
        "requirement": None,
        "history": [
            {
                "action": "init",
                "from": None,
                "to": "draft",
                "at": timestamp,
            }
        ],
    }
    _atomic_json_write(root, path, data)
    return data, True


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise StateError(f"cannot read requirement document {path}: {exc}") from exc
    return digest.hexdigest()


def _requirement_path(root: Path, value: Optional[str]) -> Tuple[Path, str]:
    candidate = Path(value) if value else Path(DEFAULT_REQUIREMENT)
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        lexical_relative = candidate.relative_to(root)
    except ValueError:
        lexical_relative = None
    if lexical_relative and lexical_relative.parts and lexical_relative.parts[0] == AGENT_DIR:
        candidate = secure_workspace_path(root, *lexical_relative.parts[1:])
    resolved = candidate.expanduser().resolve()
    try:
        relative = resolved.relative_to(root)
    except ValueError as exc:
        raise StateError("requirement document must be inside the project root") from exc
    if not resolved.is_file():
        raise StateError(f"requirement document does not exist: {resolved}")
    return resolved, relative.as_posix()


def requirement_integrity(root: Path, data: Dict[str, Any]) -> Dict[str, Any]:
    metadata = data.get("requirement")
    if not metadata:
        try:
            draft_path = secure_workspace_path(root, "requirement.md")
        except StateError as exc:
            return {
                "checked": False,
                "integrity": None,
                "reason": str(exc),
                "path": DEFAULT_REQUIREMENT,
                "approved_sha256": None,
                "current_sha256": None,
            }
        current_hash = sha256_file(draft_path) if draft_path.is_file() else None
        return {
            "checked": False,
            "integrity": None,
            "reason": "no approved requirement is recorded",
            "path": DEFAULT_REQUIREMENT,
            "approved_sha256": None,
            "current_sha256": current_hash,
        }
    relative = metadata.get("path")
    approved_hash = metadata.get("sha256")
    if not isinstance(relative, str) or not isinstance(approved_hash, str):
        return {
            "checked": True,
            "integrity": False,
            "reason": "approved requirement metadata is invalid",
            "path": relative,
            "approved_sha256": approved_hash,
            "current_sha256": None,
        }
    raw_path = root / relative
    try:
        lexical_relative = raw_path.relative_to(root)
        if lexical_relative.parts and lexical_relative.parts[0] == AGENT_DIR:
            raw_path = secure_workspace_path(root, *lexical_relative.parts[1:])
    except (ValueError, StateError) as exc:
        return {
            "checked": True,
            "integrity": False,
            "reason": str(exc),
            "path": relative,
            "approved_sha256": approved_hash,
            "current_sha256": None,
        }
    path = raw_path.resolve()
    try:
        path.relative_to(root)
    except ValueError:
        return {
            "checked": True,
            "integrity": False,
            "reason": "approved requirement path escapes the project root",
            "path": relative,
            "approved_sha256": approved_hash,
            "current_sha256": None,
        }
    if not path.is_file():
        return {
            "checked": True,
            "integrity": False,
            "reason": f"approved requirement is missing: {relative}",
            "path": relative,
            "approved_sha256": approved_hash,
            "current_sha256": None,
        }
    current_hash = sha256_file(path)
    matches = current_hash == approved_hash
    return {
        "checked": True,
        "integrity": matches,
        "reason": "unchanged" if matches else "requirement changed after approval",
        "path": relative,
        "approved_sha256": approved_hash,
        "current_sha256": current_hash,
    }


def _assert_requirement_unchanged(root: Path, data: Dict[str, Any]) -> None:
    result = requirement_integrity(root, data)
    if result["integrity"] is not True:
        raise StateError(
            f"approved requirement integrity check failed: {result['reason']}; "
            "do not continue implementation"
        )


def assert_requirement_unchanged(root: Path, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Public integrity gate used by the command and verification runtimes."""
    state_data = data if data is not None else load_state(root)
    _assert_requirement_unchanged(root, state_data)
    return state_data


RUN_PAIR_FIELDS = (
    "schema_version",
    "run_id",
    "phase",
    "argv",
    "cwd",
    "source",
    "background",
    "argv_redacted",
    "started_at",
    "workflow_state",
    "approved_requirement_sha256",
)


def _read_json_object(path: Path, label: str) -> Dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StateError(f"cannot read {label} {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise StateError(f"invalid {label} (expected object): {path}")
    return value


def _load_run_attempt(root: Path, run_id: str) -> Dict[str, Any]:
    if not isinstance(run_id, str) or not run_id or Path(run_id).name != run_id:
        raise StateError("invalid run id in execution evidence")
    run_dir = secure_workspace_path(root, RUNS_DIR, run_id)
    if not run_dir.is_dir():
        raise StateError(f"execution evidence directory is missing: {run_dir}")
    command_path = secure_workspace_path(root, RUNS_DIR, run_id, "command.json")
    result_path = secure_workspace_path(root, RUNS_DIR, run_id, "result.json")
    command = _read_json_object(command_path, "command evidence")
    if command.get("run_id") != run_id:
        raise StateError(f"command evidence run id does not match its directory: {run_id}")
    if not result_path.is_file():
        raise StateError(f"execution result is missing for run {run_id}")
    result = _read_json_object(result_path, "execution result")
    mismatched = [field for field in RUN_PAIR_FIELDS if result.get(field) != command.get(field)]
    if mismatched:
        raise StateError(
            f"execution result does not match command evidence for run {run_id}: "
            + ", ".join(mismatched)
        )
    if result.get("run_id") != run_id:
        raise StateError(f"execution result run id does not match its directory: {run_id}")
    return {
        "run_id": run_id,
        "command": command,
        "result": result,
        "result_path": str(result_path.relative_to(root)),
        "result_sha256": sha256_file(result_path),
    }


def _matching_run_attempts(
    root: Path,
    phase: str,
    approved_hash: str,
    workflow_state: str,
) -> List[Dict[str, Any]]:
    runs_dir = secure_workspace_path(root, RUNS_DIR)
    if not runs_dir.exists():
        return []
    if not runs_dir.is_dir():
        raise StateError(f"execution evidence path is not a directory: {runs_dir}")
    attempts: List[Dict[str, Any]] = []
    for run_dir in sorted(runs_dir.iterdir(), key=lambda item: item.name):
        if run_dir.is_symlink():
            raise StateError(f"execution evidence directory must not be a symbolic link: {run_dir}")
        if not run_dir.is_dir():
            continue
        command_path = secure_workspace_path(root, RUNS_DIR, run_dir.name, "command.json")
        if not command_path.is_file():
            continue
        try:
            command = _read_json_object(command_path, "command evidence")
        except StateError:
            # A corrupt unrelated run cannot be associated with this phase/hash.
            continue
        if (
            command.get("phase") != phase
            or command.get("approved_requirement_sha256") != approved_hash
            or command.get("workflow_state") != workflow_state
        ):
            continue
        attempts.append(_load_run_attempt(root, run_dir.name))
    return attempts


def _latest_run_attempt(
    root: Path,
    phase: str,
    approved_hash: str,
    workflow_state: str,
) -> Optional[Dict[str, Any]]:
    attempts = _matching_run_attempts(root, phase, approved_hash, workflow_state)
    return max(attempts, key=lambda item: item["run_id"]) if attempts else None


def _completed_successfully(attempt: Dict[str, Any]) -> bool:
    result = attempt["result"]
    return result.get("status") == "completed" and result.get("exit_code") == 0


def _assert_build_evidence(root: Path, data: Dict[str, Any]) -> Dict[str, Any]:
    approved_hash = (data.get("requirement") or {}).get("sha256")
    if not isinstance(approved_hash, str):
        raise StateError("cannot validate build evidence without an approved requirement hash")
    try:
        commands = detect_project(root).get("commands", {})
    except (OSError, ValueError, TypeError) as exc:
        raise StateError(f"cannot detect project commands while validating build evidence: {exc}") from exc

    evidence: Dict[str, Any] = {}
    missing: List[str] = []
    for phase in ("install", "build", "test"):
        attempt = _latest_run_attempt(root, phase, approved_hash, "implementing")
        detected_count = len(commands.get(phase, [])) if isinstance(commands.get(phase, []), list) else 0
        required = phase in {"build", "test"} and detected_count > 0
        if attempt is None:
            if required:
                missing.append(f"{phase} (detected candidates: {detected_count})")
                evidence[phase] = {"status": "missing", "detected_candidates": detected_count}
            else:
                evidence[phase] = {
                    "status": "not_run" if phase == "install" and detected_count else "not_applicable",
                    "detected_candidates": detected_count,
                }
            continue
        result = attempt["result"]
        evidence[phase] = {
            "status": "passed" if _completed_successfully(attempt) else "failed",
            "run_id": attempt["run_id"],
            "result_path": attempt["result_path"],
            "result_sha256": attempt["result_sha256"],
            "exit_code": result.get("exit_code"),
            "detected_candidates": detected_count,
        }
        if not _completed_successfully(attempt):
            missing.append(
                f"{phase} (latest run {attempt['run_id']} is {result.get('status')!r}, "
                f"exit {result.get('exit_code')!r})"
            )
    if missing:
        raise StateError(
            "cannot enter 'built' without current successful phase evidence: " + "; ".join(missing)
        )
    return evidence


def _process_alive(pid: Any) -> bool:
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return False
    if os.name == "nt":
        # os.kill(pid, 0) is not a portable existence probe on Windows and may
        # terminate the target. Query the process handle without modifying it.
        try:
            import ctypes
            from ctypes import wintypes

            process_query_limited_information = 0x1000
            still_active = 259
            kernel32 = ctypes.windll.kernel32
            kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel32.OpenProcess.restype = wintypes.HANDLE
            kernel32.GetExitCodeProcess.argtypes = [
                wintypes.HANDLE,
                ctypes.POINTER(wintypes.DWORD),
            ]
            kernel32.GetExitCodeProcess.restype = wintypes.BOOL
            kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel32.CloseHandle.restype = wintypes.BOOL
            handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
            if not handle:
                return False
            try:
                exit_code = wintypes.DWORD()
                if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                    return False
                return exit_code.value == still_active
            finally:
                kernel32.CloseHandle(handle)
        except (AttributeError, OSError):
            return False
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except OSError:
        return False


def _compose_up_mode(argv: Any) -> Tuple[bool, bool]:
    if not isinstance(argv, list) or not argv:
        return False, False
    executable = str(argv[0]).replace("\\", "/").rsplit("/", 1)[-1].lower()
    is_compose = executable in {"docker-compose", "docker-compose.exe"}
    if executable in {"docker", "docker.exe"} and len(argv) > 1:
        is_compose = str(argv[1]).lower() == "compose"
    lowered = [str(item).lower() for item in argv]
    is_compose_up = is_compose and "up" in lowered
    detached = is_compose_up and any(item in {"-d", "--detach"} for item in lowered)
    return is_compose_up, detached


def _classify_start_attempt(attempt: Dict[str, Any]) -> Tuple[str, Optional[bool]]:
    result = attempt["result"]
    background = result.get("background") is True
    if background:
        alive = _process_alive(result.get("pid"))
        if result.get("status") != "running" or result.get("exit_code") is not None or not alive:
            raise StateError(
                f"background start run {attempt['run_id']} is not a live process "
                f"(status={result.get('status')!r}, exit={result.get('exit_code')!r})"
            )
        return "background_process", alive

    if not _completed_successfully(attempt):
        raise StateError(
            f"start run {attempt['run_id']} did not complete successfully "
            f"(status={result.get('status')!r}, exit={result.get('exit_code')!r})"
        )
    compose_up, detached = _compose_up_mode(result.get("argv"))
    if compose_up and not detached:
        raise StateError(
            "a foreground Docker Compose 'up' run must use --detach or remain alive in "
            "background mode before the environment can be marked running"
        )
    return ("compose_detached" if compose_up else "one_shot_cli"), None


def _assert_start_evidence(root: Path, data: Dict[str, Any]) -> Dict[str, Any]:
    approved_hash = (data.get("requirement") or {}).get("sha256")
    if not isinstance(approved_hash, str):
        raise StateError("cannot validate start evidence without an approved requirement hash")
    attempt = _latest_run_attempt(root, "start", approved_hash, "built")
    if attempt is None:
        raise StateError(
            "cannot enter 'running' without a current successful start run recorded after 'built'"
        )
    kind, process_alive = _classify_start_attempt(attempt)
    result = attempt["result"]
    return {
        "run_id": attempt["run_id"],
        "kind": kind,
        "result_path": attempt["result_path"],
        "result_sha256": attempt["result_sha256"],
        "started_at": result.get("started_at"),
        "background": result.get("background"),
        "pid": result.get("pid"),
        "process_group_id": result.get("process_group_id"),
        "process_alive_at_binding": process_alive,
    }


def load_bound_start_evidence(root: Path, data: Dict[str, Any]) -> Dict[str, Any]:
    binding = data.get("environment_start")
    if not isinstance(binding, dict):
        raise StateError("workflow has no bound environment start evidence")
    run_id = binding.get("run_id")
    attempt = _load_run_attempt(root, run_id)
    approved_hash = (data.get("requirement") or {}).get("sha256")
    result = attempt["result"]
    if result.get("phase") != "start" or result.get("workflow_state") != "built":
        raise StateError("bound environment evidence is not a start run from the built stage")
    if result.get("approved_requirement_sha256") != approved_hash:
        raise StateError("bound environment start does not match the approved requirement hash")
    if binding.get("result_path") != attempt["result_path"]:
        raise StateError("bound environment start result path changed")
    if binding.get("result_sha256") != attempt["result_sha256"]:
        raise StateError("bound environment start result was modified after entering 'running'")
    kind, process_alive = _classify_start_attempt(attempt)
    if binding.get("kind") != kind:
        raise StateError("bound environment start kind does not match its execution result")
    return {
        "run_id": attempt["run_id"],
        "kind": kind,
        "result_path": attempt["result_path"],
        "result_sha256": attempt["result_sha256"],
        "status": result.get("status"),
        "exit_code": result.get("exit_code"),
        "pid": result.get("pid"),
        "process_group_id": result.get("process_group_id"),
        "process_alive": process_alive,
        "background": result.get("background"),
        "argv": result.get("argv") if isinstance(result.get("argv"), list) else [],
        "started_at": result.get("started_at"),
        "stdout_path": result.get("stdout_path"),
        "stderr_path": result.get("stderr_path"),
        "approved_requirement_sha256": result.get("approved_requirement_sha256"),
        "matches_approved_requirement": result.get("approved_requirement_sha256") == approved_hash,
        "valid": True,
    }


def _valid_receipt_test_run(root: Path, value: Any, approved_hash: str) -> bool:
    if not isinstance(value, dict) or not isinstance(value.get("run_id"), str):
        return False
    try:
        attempt = _load_run_attempt(root, value["run_id"])
    except StateError:
        return False
    result = attempt["result"]
    return (
        result.get("phase") == "test"
        and result.get("approved_requirement_sha256") == approved_hash
        and _completed_successfully(attempt)
        and value.get("result_path") == attempt["result_path"]
        and value.get("result_sha256") == attempt["result_sha256"]
        and value.get("status") == result.get("status")
        and value.get("exit_code") == result.get("exit_code")
    )


def _assert_successful_verification(root: Path, data: Dict[str, Any]) -> Dict[str, Any]:
    receipt_path = secure_workspace_path(root, "environment.json")
    if not receipt_path.is_file():
        raise StateError(
            f"cannot enter 'verified' without a successful receipt at {ENVIRONMENT_RECEIPT}"
        )
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StateError(f"cannot read verification receipt {receipt_path}: {exc}") from exc
    if (
        not isinstance(receipt, dict)
        or receipt.get("passed") is not True
        or receipt.get("status") != "passed"
    ):
        raise StateError("cannot enter 'verified': latest environment receipt did not pass")
    expected_hash = (data.get("requirement") or {}).get("sha256")
    if receipt.get("approved_requirement_sha256") != expected_hash:
        raise StateError(
            "cannot enter 'verified': environment receipt does not match the approved requirement hash"
        )
    if receipt.get("project_root") != str(root):
        raise StateError(
            "cannot enter 'verified': environment receipt belongs to a different project root"
        )
    if receipt.get("workflow_state") != "running":
        raise StateError(
            "cannot enter 'verified': environment receipt was not created from the running stage"
        )
    bound_start = load_bound_start_evidence(root, data)
    receipt_start = receipt.get("start_run")
    if not isinstance(receipt_start, dict):
        raise StateError("cannot enter 'verified': receipt has no bound start evidence")
    for field in (
        "run_id",
        "kind",
        "result_path",
        "result_sha256",
        "status",
        "exit_code",
        "pid",
        "process_group_id",
        "background",
        "argv",
        "started_at",
    ):
        if receipt_start.get(field) != bound_start.get(field):
            raise StateError(
                f"cannot enter 'verified': receipt start field {field!r} does not match "
                "the bound execution result"
            )
    if receipt_start.get("valid") is not True:
        raise StateError("cannot enter 'verified': receipt marks its start evidence invalid")

    http_checks = receipt.get("http_checks")
    http_valid = (
        isinstance(http_checks, list)
        and bool(http_checks)
        and all(isinstance(item, dict) and item.get("passed") is True for item in http_checks)
    )
    test_valid = _valid_receipt_test_run(root, receipt.get("test_run"), expected_hash)
    if not http_valid and not test_valid:
        raise StateError(
            "cannot enter 'verified': receipt has neither successful HTTP checks nor a "
            "traceable successful acceptance test"
        )
    if bound_start["kind"] == "one_shot_cli" and not test_valid:
        raise StateError(
            "cannot enter 'verified': a one-shot CLI environment requires a traceable "
            "successful acceptance test"
        )
    return receipt


def transition_state(root: Path, target: str, note: Optional[str] = None) -> Dict[str, Any]:
    if target not in STATES:
        raise StateError(f"unknown target state {target!r}; choose one of: {', '.join(STATES)}")
    data = load_state(root)
    current = data["state"]
    if target == "approved":
        raise StateError("approval must use the 'approve' command so the requirement hash is recorded")
    expected = NEXT_STATE.get(current)
    if target != expected:
        if expected is None:
            raise StateError(f"workflow is already terminal at {current!r}")
        raise StateError(
            f"illegal transition {current!r} -> {target!r}; the only next state is {expected!r}"
        )
    if current == "draft" and target == "awaiting_approval":
        requirement_path, _ = _requirement_path(root, None)
        if requirement_path.stat().st_size == 0:
            raise StateError("requirement document is empty; write it before requesting approval")
    if current in APPROVED_STATES:
        _assert_requirement_unchanged(root, data)
    build_evidence: Optional[Dict[str, Any]] = None
    start_evidence: Optional[Dict[str, Any]] = None
    receipt: Optional[Dict[str, Any]] = None
    if current == "implementing" and target == "built":
        build_evidence = _assert_build_evidence(root, data)
    if current == "built" and target == "running":
        start_evidence = _assert_start_evidence(root, data)
    if current == "running" and target == "verified":
        receipt = _assert_successful_verification(root, data)
    timestamp = utc_now()
    event: Dict[str, Any] = {
        "action": "transition",
        "from": current,
        "to": target,
        "at": timestamp,
    }
    if note:
        event["note"] = note
    if build_evidence is not None:
        data["build_evidence"] = build_evidence
        event["build_evidence"] = build_evidence
    if start_evidence is not None:
        data["environment_start"] = start_evidence
        event["environment_start"] = start_evidence
    if receipt is not None:
        event["verification_receipt"] = ENVIRONMENT_RECEIPT
        event["verification_receipt_at"] = receipt.get("verified_at")
    data["state"] = target
    data["updated_at"] = timestamp
    data["history"].append(event)
    _atomic_json_write(root, state_path(root), data)
    return data


def approve_requirement(
    root: Path,
    expected_sha256: str,
    requirement: Optional[str] = None,
    note: Optional[str] = None,
) -> Dict[str, Any]:
    data = load_state(root)
    if data["state"] != "awaiting_approval":
        raise StateError(
            "requirement approval is only allowed from 'awaiting_approval'; "
            f"current state is {data['state']!r}"
        )
    path, relative = _requirement_path(root, requirement)
    if path.stat().st_size == 0:
        raise StateError("requirement document is empty and cannot be approved")
    timestamp = utc_now()
    digest = sha256_file(path)
    normalized_expected = expected_sha256.strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", normalized_expected):
        raise StateError("--expected-sha256 must be exactly 64 hexadecimal characters")
    if digest != normalized_expected:
        raise StateError(
            "requirement changed or the wrong hash was approved: "
            f"expected {normalized_expected}, current {digest}"
        )
    metadata = {
        "path": relative,
        "sha256": digest,
        "size_bytes": path.stat().st_size,
        "approved_at": timestamp,
    }
    event: Dict[str, Any] = {
        "action": "approve",
        "from": "awaiting_approval",
        "to": "approved",
        "at": timestamp,
        "requirement_path": relative,
        "requirement_sha256": digest,
    }
    if note:
        event["note"] = note
    data["state"] = "approved"
    data["updated_at"] = timestamp
    data["requirement"] = metadata
    data["history"].append(event)
    _atomic_json_write(root, state_path(root), data)
    return data


def revise_requirement(root: Path, note: Optional[str] = None) -> Dict[str, Any]:
    """Reopen an approved but not-yet-started requirement for editing."""
    data = load_state(root)
    if data["state"] != "approved":
        raise StateError(
            "revision is only allowed while state is 'approved' and implementation has not started; "
            f"current state is {data['state']!r}"
        )
    timestamp = utc_now()
    previous = data.get("requirement") or {}
    event: Dict[str, Any] = {
        "action": "revise",
        "from": "approved",
        "to": "awaiting_approval",
        "at": timestamp,
        "previous_requirement_sha256": previous.get("sha256"),
    }
    if note:
        event["note"] = note
    data["state"] = "awaiting_approval"
    data["updated_at"] = timestamp
    data["requirement"] = None
    data["history"].append(event)
    _atomic_json_write(root, state_path(root), data)
    return data


def state_for_display(root: Path, data: Dict[str, Any]) -> Dict[str, Any]:
    result = dict(data)
    integrity = requirement_integrity(root, data)
    result["requirement_integrity"] = integrity
    relative = integrity.get("path") or DEFAULT_REQUIREMENT
    current_path = (root / relative).resolve()
    try:
        current_path.relative_to(root)
        inside_root = True
    except ValueError:
        inside_root = False
    exists = inside_root and current_path.is_file()
    current_requirement: Dict[str, Any] = {
        "path": relative,
        "exists": exists,
        "sha256": integrity.get("current_sha256"),
        "size_bytes": current_path.stat().st_size if exists else None,
    }
    result["current_requirement"] = current_requirement
    result["allowed_next_state"] = NEXT_STATE.get(data["state"])
    if result["allowed_next_state"] == "approved":
        result["allowed_next_action"] = "approve"
    elif result["allowed_next_state"]:
        result["allowed_next_action"] = "transition"
    else:
        result["allowed_next_action"] = None
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="target project root (default: current directory)")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init", help="initialize an idempotent workflow in draft state")
    commands.add_parser("show", help="print state and requirement integrity as JSON")

    transition = commands.add_parser("transition", help="move to the one permitted next state")
    transition.add_argument("target", choices=STATES)
    transition.add_argument("--note", help="optional audit note")

    approve = commands.add_parser("approve", help="approve and hash the requirement document")
    approve.add_argument(
        "--requirement",
        help=f"path inside project root (default: {DEFAULT_REQUIREMENT})",
    )
    approve.add_argument(
        "--expected-sha256",
        required=True,
        help="exact SHA-256 shown to and explicitly approved by the user",
    )
    approve.add_argument("--note", help="optional audit note")

    revise = commands.add_parser(
        "revise", help="reopen an approved, not-yet-implemented requirement for editing"
    )
    revise.add_argument("--note", help="optional audit note")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(argv)
    try:
        root = project_root(args.root)
        if args.command == "init":
            data, created = init_state(root)
            output = state_for_display(root, data)
            output["created"] = created
        elif args.command == "show":
            output = state_for_display(root, load_state(root))
        elif args.command == "transition":
            output = state_for_display(root, transition_state(root, args.target, args.note))
        elif args.command == "approve":
            output = state_for_display(
                root,
                approve_requirement(
                    root,
                    args.expected_sha256,
                    requirement=args.requirement,
                    note=args.note,
                ),
            )
        elif args.command == "revise":
            output = state_for_display(root, revise_requirement(root, args.note))
        else:  # pragma: no cover - guarded by argparse
            raise AssertionError(args.command)
        print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except StateError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
