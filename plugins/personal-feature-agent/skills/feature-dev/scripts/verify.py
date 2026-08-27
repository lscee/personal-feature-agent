#!/usr/bin/env python3
"""Verify a development environment and write a machine/human-readable receipt.

At least one HTTP URL or test command is required. HTTP checks use urllib from
the standard library; test commands follow the same detected-candidate policy
as run_command.py. This script never changes workflow state implicitly.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import shlex
import socket
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

try:
    from .run_command import RunnerError, execute_command, select_command
except ImportError:  # Executed as a standalone script.
    from run_command import RunnerError, execute_command, select_command

try:
    from .state import (
        STATES,
        StateError,
        assert_requirement_unchanged,
        load_bound_start_evidence,
        load_state,
        private_atomic_write,
        secure_workspace_path,
        sha256_file,
    )
except ImportError:  # Executed as a standalone script.
    from state import (
        STATES,
        StateError,
        assert_requirement_unchanged,
        load_bound_start_evidence,
        load_state,
        private_atomic_write,
        secure_workspace_path,
        sha256_file,
    )


SCHEMA_VERSION = 1
AGENT_DIR = ".feature-agent"
JSON_RECEIPT = "environment.json"
MARKDOWN_RECEIPT = "environment.md"


class VerificationError(RuntimeError):
    """An invalid verification request."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _atomic_write(root: Path, path: Path, content: str) -> None:
    try:
        private_atomic_write(root, path, content)
    except (OSError, StateError) as exc:
        raise VerificationError(f"unsafe feature-agent receipt path: {exc}") from exc


def _parse_expected_status(value: str) -> List[Tuple[int, int]]:
    ranges: List[Tuple[int, int]] = []
    for part in value.split(","):
        token = part.strip()
        if not token:
            continue
        if "-" in token:
            start_text, end_text = token.split("-", 1)
        else:
            start_text = end_text = token
        try:
            start, end = int(start_text), int(end_text)
        except ValueError as exc:
            raise VerificationError(f"invalid expected HTTP status: {token!r}") from exc
        if not (100 <= start <= end <= 599):
            raise VerificationError(f"expected HTTP status is outside 100..599: {token!r}")
        ranges.append((start, end))
    if not ranges:
        raise VerificationError("at least one expected HTTP status is required")
    return ranges


def _status_expected(status: int, ranges: Sequence[Tuple[int, int]]) -> bool:
    return any(start <= status <= end for start, end in ranges)


def _url_is_remote(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise VerificationError("health-check URL must be absolute HTTP(S)")
    if parsed.username is not None or parsed.password is not None:
        raise VerificationError("health-check URLs must not contain user information")
    try:
        parsed.port
    except ValueError as exc:
        raise VerificationError("health-check URL has an invalid port") from exc
    host = parsed.hostname.rstrip(".").lower()
    if host == "localhost":
        return False
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return True
    if address.is_loopback:
        return False
    if address.is_link_local or address.is_multicast or address.is_unspecified or address.is_reserved:
        raise VerificationError(f"health-check URL uses a blocked special-purpose address: {host}")
    return True


def _validate_resolved_addresses(url: str) -> None:
    parsed = urlparse(url)
    host = parsed.hostname
    if not host:
        return
    try:
        ipaddress.ip_address(host)
        return
    except ValueError:
        pass
    try:
        addresses = socket.getaddrinfo(host, parsed.port, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return  # urllib will report the connection/DNS failure as verification evidence.
    for item in addresses:
        try:
            address = ipaddress.ip_address(item[4][0])
        except ValueError:
            continue
        if address.is_loopback:
            continue
        if address.is_link_local or address.is_multicast or address.is_unspecified or address.is_reserved:
            raise VerificationError(
                f"health-check host resolves to a blocked special-purpose address: {address}"
            )


def _redact_url(url: Optional[str]) -> Optional[str]:
    if url is None:
        return None
    parsed = urlsplit(url)
    hostname = parsed.hostname or ""
    netloc = hostname
    if parsed.port is not None:
        netloc = f"{netloc}:{parsed.port}"
    if ":" in hostname and not hostname.startswith("["):
        netloc = f"[{hostname}]" + (f":{parsed.port}" if parsed.port is not None else "")
    query = ""
    if parsed.query:
        query = "redacted=%3Credacted%3E"
    return urlunsplit((parsed.scheme, netloc, parsed.path, query, ""))


def _validate_url_policy(url: str, allow_remote_url: bool) -> bool:
    remote = _url_is_remote(url)
    if remote and not allow_remote_url:
        raise VerificationError(
            f"refusing non-local development URL {_redact_url(url)!r}; "
            "pass --allow-remote-url only "
            "after confirming it is a safe non-production target"
        )
    if remote:
        _validate_resolved_addresses(url)
    return remote


class _GuardedRedirectHandler(HTTPRedirectHandler):
    def __init__(self, allow_remote_url: bool) -> None:
        super().__init__()
        self.allow_remote_url = allow_remote_url

    def redirect_request(
        self,
        req: Any,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> Any:
        _validate_url_policy(newurl, self.allow_remote_url)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def http_check(
    url: str,
    expected: Sequence[Tuple[int, int]],
    timeout: float,
    allow_remote_url: bool = False,
) -> Dict[str, Any]:
    remote = _validate_url_policy(url, allow_remote_url)
    if timeout <= 0:
        raise VerificationError("HTTP timeout must be greater than zero")
    started = time.monotonic()
    deadline = started + timeout
    request = Request(url, headers={"User-Agent": "personal-feature-agent/1"})
    opener = build_opener(_GuardedRedirectHandler(allow_remote_url))
    attempts = 0
    status: Optional[int] = None
    final_url: Optional[str] = None
    error: Optional[str] = None
    passed = False

    while True:
        attempts += 1
        status = None
        final_url = None
        error = None
        remaining = max(0.001, deadline - time.monotonic())
        try:
            with opener.open(request, timeout=remaining) as response:
                status = response.getcode()
                final_url = response.geturl()
                response.read(1)
        except HTTPError as exc:
            status = exc.code
            final_url = exc.geturl()
            error = None if _status_expected(status, expected) else f"HTTP status {status}"
        except (URLError, TimeoutError, OSError) as exc:
            error = str(exc).replace(url, _redact_url(url) or "<redacted-url>")

        passed = status is not None and _status_expected(status, expected) and error is None
        if status is not None and not passed and error is None:
            error = f"HTTP status {status}"
        if passed:
            break

        transient_status = status in {408, 425, 429} or (
            isinstance(status, int) and 500 <= status <= 599
        )
        retryable = status is None or transient_status or (
            error is not None and status is not None and _status_expected(status, expected)
        )
        remaining = deadline - time.monotonic()
        if not retryable or remaining <= 0:
            break
        time.sleep(min(0.1, remaining))

    return {
        "kind": "http",
        "url": _redact_url(url),
        "remote_url": remote,
        "final_url": _redact_url(final_url),
        "status": status,
        "expected_status": [
            str(start) if start == end else f"{start}-{end}" for start, end in expected
        ],
        "attempts": attempts,
        "passed": passed,
        "duration_seconds": round(time.monotonic() - started, 3),
        "error": error,
    }


def _markdown_cell(value: Any) -> str:
    if value is None:
        return "—"
    return str(value).replace("|", "\\|").replace("\n", " ")


def _bound_start_run(root: Path, workflow: Dict[str, Any]) -> Dict[str, Any]:
    try:
        start = load_bound_start_evidence(root, workflow)
    except StateError as exc:
        raise VerificationError(f"invalid bound start evidence: {exc}") from exc
    pid = start.get("pid")
    argv = start.get("argv") if isinstance(start.get("argv"), list) else []
    is_docker = start.get("kind") == "compose_detached"
    stop_hint: Dict[str, Any]
    if start.get("background") is True and isinstance(pid, int) and not is_docker:
        process_group_id = start.get("process_group_id")
        stop_argv = (
            ["taskkill", "/PID", str(pid), "/T"]
            if os.name == "nt"
            else ["kill", "-TERM", f"-{process_group_id or pid}"]
        )
        stop_hint = {
            "kind": "process_group" if os.name != "nt" else "process_tree",
            "argv": stop_argv,
            "note": (
                "Confirm the PID/process group still belongs to this development environment "
                "before stopping it."
            ),
        }
    else:
        stop_hint = {
            "kind": "project-specific",
            "argv": None,
            "note": (
                "Use the repository's documented shutdown command. No shutdown command was "
                "inferred from the start command."
            ),
        }
    return {**start, "stop_hint": stop_hint}


def markdown_receipt(receipt: Dict[str, Any]) -> str:
    status = "PASS" if receipt["passed"] else "FAIL"
    lines = [
        "# Development Environment Receipt",
        "",
        f"- Status: **{status}**",
        f"- Verified at: `{receipt['verified_at']}`",
        f"- Project root: `{receipt['project_root']}`",
        "",
        "## HTTP checks",
        "",
    ]
    if receipt["http_checks"]:
        lines.extend(
            [
                "| URL | Status | Expected | Result | Duration |",
                "| --- | ---: | --- | --- | ---: |",
            ]
        )
        for check in receipt["http_checks"]:
            lines.append(
                "| {url} | {status} | {expected} | {result} | {duration}s |".format(
                    url=_markdown_cell(check["url"]),
                    status=_markdown_cell(check["status"]),
                    expected=_markdown_cell(", ".join(check["expected_status"])),
                    result="PASS" if check["passed"] else f"FAIL: {_markdown_cell(check['error'])}",
                    duration=check["duration_seconds"],
                )
            )
    else:
        lines.append("No HTTP URL was supplied.")
    lines.extend(["", "## Test command", ""])
    test_run = receipt.get("test_run")
    if test_run:
        lines.extend(
            [
                f"- Result: **{'PASS' if test_run['exit_code'] == 0 else 'FAIL'}**",
                f"- Command: `{' '.join(test_run['argv'])}`",
                f"- Exit code: `{test_run['exit_code']}`",
                f"- Duration: `{test_run['duration_seconds']}s`",
                f"- Stdout: `{test_run['stdout_path']}`",
                f"- Stderr: `{test_run['stderr_path']}`",
            ]
        )
    else:
        lines.append("No test command was supplied.")
    lines.extend(["", "## Start evidence and shutdown", ""])
    start_run = receipt.get("start_run")
    if start_run:
        lines.extend(
            [
                f"- Run: `{_markdown_cell(start_run['run_id'])}`",
                f"- Command: `{_markdown_cell(shlex.join(start_run['argv']))}`",
                f"- Status: `{_markdown_cell(start_run['status'])}`",
                f"- PID: `{_markdown_cell(start_run['pid'])}`",
                f"- Process alive at verification: `{_markdown_cell(start_run['process_alive'])}`",
                f"- Stdout: `{_markdown_cell(start_run['stdout_path'])}`",
                f"- Stderr: `{_markdown_cell(start_run['stderr_path'])}`",
            ]
        )
        stop_hint = start_run["stop_hint"]
        if stop_hint.get("argv"):
            lines.append(f"- Stop hint: `{shlex.join(stop_hint['argv'])}`")
        lines.append(f"- Stop note: {_markdown_cell(stop_hint['note'])}")
    else:
        lines.append(
            "No audited start run was found. Use the repository's documented shutdown procedure."
        )
    lines.extend(
        [
            "",
            "## Machine-readable receipt",
            "",
            f"See `{AGENT_DIR}/{JSON_RECEIPT}`.",
            "",
        ]
    )
    return "\n".join(lines)


def verify_environment(
    root: Path,
    urls: Sequence[str],
    expected_status: str,
    http_timeout: float,
    *,
    test_candidate: Optional[int] = None,
    test_argv: Sequence[str] = (),
    allow_unknown: bool = False,
    command_timeout: Optional[float] = None,
    allow_remote_url: bool = False,
) -> Dict[str, Any]:
    root = root.expanduser().resolve()
    if not root.is_dir():
        raise VerificationError(f"project root is not a directory: {root}")
    explicit = list(test_argv)
    if explicit and explicit[0] == "--":
        explicit = explicit[1:]
    if not urls and test_candidate is None and not explicit:
        raise VerificationError("provide at least one --url or a test command")
    try:
        workflow = load_state(root)
        if STATES.index(workflow["state"]) < STATES.index("running"):
            raise VerificationError(
                "environment verification requires workflow state 'running' or later; "
                f"current state is {workflow['state']!r}"
            )
        assert_requirement_unchanged(root, workflow)
        start_run = _bound_start_run(root, workflow)
    except StateError as exc:
        raise VerificationError(f"workflow gate rejected verification: {exc}") from exc
    expected = _parse_expected_status(expected_status)
    checks = [
        http_check(url, expected, http_timeout, allow_remote_url=allow_remote_url)
        for url in urls
    ]

    test_run: Optional[Dict[str, Any]] = None
    if test_candidate is not None or explicit:
        try:
            argv, cwd, source, known, index = select_command(
                root, "test", test_candidate, explicit, allow_unknown
            )
            test_run = dict(execute_command(
                root,
                "test",
                argv,
                cwd=cwd,
                source=source,
                known_candidate=known,
                unknown_approved=allow_unknown and not known,
                candidate_index=index,
                timeout=command_timeout,
            ))
            result_relative = Path(test_run["result_path"])
            if not result_relative.parts or result_relative.parts[0] != AGENT_DIR:
                raise VerificationError("test evidence path is outside the feature-agent workspace")
            result_path = secure_workspace_path(root, *result_relative.parts[1:])
            test_run["result_sha256"] = sha256_file(result_path)
        except (RunnerError, StateError) as exc:
            raise VerificationError(str(exc)) from exc

    checks_passed = all(check["passed"] for check in checks)
    test_passed = test_run is None or (
        test_run.get("status") == "completed" and test_run.get("exit_code") == 0
    )
    acceptance_present = bool(checks) or test_run is not None
    one_shot_has_test = start_run.get("kind") != "one_shot_cli" or (
        test_run is not None and test_passed
    )
    passed = checks_passed and test_passed and acceptance_present and one_shot_has_test
    approved_hash = (workflow.get("requirement") or {}).get("sha256")
    receipt: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "project_root": str(root),
        "verified_at": utc_now(),
        "status": "passed" if passed else "failed",
        "passed": passed,
        "workflow_state": workflow["state"],
        "approved_requirement_sha256": approved_hash,
        "remote_url_allowed": allow_remote_url,
        "urls": list(dict.fromkeys(_redact_url(url) for url in urls)),
        "http_checks": checks,
        "test_run": test_run,
        "start_run": start_run,
        "artifacts": {
            "markdown": f"{AGENT_DIR}/{MARKDOWN_RECEIPT}",
            "json": f"{AGENT_DIR}/{JSON_RECEIPT}",
        },
    }
    try:
        json_path = secure_workspace_path(root, JSON_RECEIPT)
        markdown_path = secure_workspace_path(root, MARKDOWN_RECEIPT)
    except StateError as exc:
        raise VerificationError(f"unsafe feature-agent receipt path: {exc}") from exc
    _atomic_write(
        root,
        json_path,
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    _atomic_write(root, markdown_path, markdown_receipt(receipt))
    return receipt


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog="Explicit test example: verify.py --root . --allow-unknown -- python3 -m unittest",
    )
    parser.add_argument("--root", default=".", help="target project root (default: current directory)")
    parser.add_argument("--url", action="append", default=[], help="HTTP(S) health URL; repeatable")
    parser.add_argument(
        "--expect-status",
        default="200-399",
        help="comma-separated status values/ranges (default: 200-399)",
    )
    parser.add_argument("--http-timeout", type=float, default=10.0, help="per-URL timeout seconds")
    parser.add_argument(
        "--allow-remote-url",
        action="store_true",
        help="allow a non-loopback URL after confirming it is a safe development target",
    )
    parser.add_argument("--test-candidate", type=int, help="detected test candidate index")
    parser.add_argument(
        "--allow-unknown",
        action="store_true",
        help="permit an explicit test command not present in detected candidates",
    )
    parser.add_argument("--command-timeout", type=float, help="test command timeout seconds")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    raw_argv = list(argv) if argv is not None else sys.argv[1:]
    test_command: List[str] = []
    if "--" in raw_argv:
        delimiter = raw_argv.index("--")
        test_command = raw_argv[delimiter + 1 :]
        raw_argv = raw_argv[:delimiter]
    args = _parser().parse_args(raw_argv)
    try:
        receipt = verify_environment(
            Path(args.root),
            args.url,
            args.expect_status,
            args.http_timeout,
            test_candidate=args.test_candidate,
            test_argv=test_command,
            allow_unknown=args.allow_unknown,
            command_timeout=args.command_timeout,
            allow_remote_url=args.allow_remote_url,
        )
        print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if receipt["passed"] else 1
    except VerificationError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
