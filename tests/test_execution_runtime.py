from __future__ import annotations

import json
import os
import signal
import stat as stat_module
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS = (
    Path(__file__).resolve().parents[1]
    / "plugins"
    / "personal-feature-agent"
    / "skills"
    / "feature-dev"
    / "scripts"
)
sys.path.insert(0, str(SCRIPTS))

import run_command  # noqa: E402
import state  # noqa: E402
import verify  # noqa: E402


class ExecutionRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        state.init_state(self.root)
        requirement = self.root / ".feature-agent" / "requirement.md"
        requirement.write_text("# Feature\n\nRuntime fixture.\n", encoding="utf-8")
        self.digest = state.sha256_file(requirement)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def approve(self) -> None:
        state.transition_state(self.root, "awaiting_approval")
        state.approve_requirement(self.root, self.digest)

    def enter_running_with_one_shot(self) -> dict:
        self.approve()
        state.transition_state(self.root, "implementing")
        state.transition_state(self.root, "built")
        start_result = run_command.execute_command(
            self.root,
            "start",
            [sys.executable, "-c", "raise SystemExit(0)"],
            known_candidate=True,
        )
        state.transition_state(self.root, "running")
        return start_result

    def test_unknown_commands_are_refused_by_default(self) -> None:
        with self.assertRaises(run_command.RunnerError):
            run_command.select_command(
                self.root,
                "build",
                candidate_index=None,
                explicit_argv=[sys.executable, "-c", "print('no')"],
                allow_unknown=False,
            )

    def test_audit_argv_redacts_common_secret_flags(self) -> None:
        redacted, changed = run_command._redact_argv(
            ["tool", "--api-key=secret-value", "--password", "hunter2", "--safe", "value"]
        )
        self.assertTrue(changed)
        self.assertEqual(
            redacted,
            ["tool", "--api-key=<redacted>", "--password", "<redacted>", "--safe", "value"],
        )

    def test_command_gate_requires_approval_and_records_output(self) -> None:
        argv = [sys.executable, "-c", "print('runtime-ok')"]
        with self.assertRaises(run_command.RunnerError):
            run_command.execute_command(
                self.root, "build", argv, known_candidate=True
            )
        self.approve()
        state.transition_state(self.root, "implementing")
        result = run_command.execute_command(
            self.root, "build", argv, known_candidate=True
        )
        self.assertEqual(result["exit_code"], 0)
        self.assertEqual(result["workflow_state"], "implementing")
        self.assertEqual(result["approved_requirement_sha256"], self.digest)
        self.assertEqual(
            (self.root / result["stdout_path"]).read_text(encoding="utf-8").strip(),
            "runtime-ok",
        )
        self.assertTrue((self.root / result["result_path"]).is_file())

    def test_runs_symlink_escape_is_rejected(self) -> None:
        self.approve()
        state.transition_state(self.root, "implementing")
        outside = self.root / "outside-runs"
        outside.mkdir()
        runs_link = self.root / ".feature-agent" / "runs"
        try:
            runs_link.symlink_to(outside, target_is_directory=True)
        except (NotImplementedError, OSError) as exc:
            self.skipTest(f"symbolic links are unavailable: {exc}")
        with self.assertRaises(run_command.RunnerError):
            run_command.execute_command(
                self.root,
                "build",
                [sys.executable, "-c", "print('must-not-run')"],
                known_candidate=True,
            )
        self.assertEqual(list(outside.iterdir()), [])

    @unittest.skipIf(os.name == "nt", "POSIX mode bits are not meaningful on Windows")
    def test_command_audit_files_use_private_permissions(self) -> None:
        self.approve()
        state.transition_state(self.root, "implementing")
        result = run_command.execute_command(
            self.root,
            "build",
            [sys.executable, "-c", "print('private-output')"],
            known_candidate=True,
        )
        run_dir = self.root / result["run_directory"]
        runs_dir = self.root / ".feature-agent" / "runs"
        self.assertEqual(stat_module.S_IMODE(runs_dir.stat().st_mode), 0o700)
        self.assertEqual(stat_module.S_IMODE(run_dir.stat().st_mode), 0o700)
        for name in ("command.json", "result.json", "stdout.log", "stderr.log"):
            self.assertEqual(stat_module.S_IMODE((run_dir / name).stat().st_mode), 0o600)

    def test_start_requires_built_state(self) -> None:
        self.approve()
        with self.assertRaises(run_command.RunnerError):
            run_command.execute_command(
                self.root,
                "start",
                [sys.executable, "-c", "print('not started')"],
                known_candidate=True,
            )

    def test_verify_requires_running_and_rejects_remote_url_by_default(self) -> None:
        self.approve()
        with self.assertRaises(verify.VerificationError):
            verify.verify_environment(self.root, ["http://127.0.0.1:1"], "200", 0.1)
        state.transition_state(self.root, "implementing")
        state.transition_state(self.root, "built")
        run_command.execute_command(
            self.root,
            "start",
            [sys.executable, "-c", "raise SystemExit(0)"],
            known_candidate=True,
        )
        state.transition_state(self.root, "running")
        with self.assertRaises(verify.VerificationError):
            verify.verify_environment(self.root, ["https://example.com"], "200", 0.1)
        with self.assertRaises(verify.VerificationError):
            verify.http_check("http://user:password@127.0.0.1:1/", [(200, 200)], 0.1)
        self.assertFalse(verify._url_is_remote("http://[::1]:8000/health"))
        with self.assertRaises(verify.VerificationError):
            verify.http_check(
                "http://169.254.169.254/latest/meta-data/",
                [(200, 200)],
                0.1,
                allow_remote_url=True,
            )

    def test_verification_receipt_symlink_target_is_rejected(self) -> None:
        self.enter_running_with_one_shot()
        outside_receipt = self.root / "outside-environment.json"
        outside_receipt.write_text("unchanged\n", encoding="utf-8")
        receipt_link = self.root / ".feature-agent" / "environment.json"
        try:
            receipt_link.symlink_to(outside_receipt)
        except (NotImplementedError, OSError) as exc:
            self.skipTest(f"symbolic links are unavailable: {exc}")
        with self.assertRaises(verify.VerificationError):
            verify.verify_environment(
                self.root,
                [],
                "200",
                0.1,
                test_argv=[sys.executable, "-c", "raise SystemExit(0)"],
                allow_unknown=True,
            )
        self.assertEqual(outside_receipt.read_text(encoding="utf-8"), "unchanged\n")

    @unittest.skipIf(os.name == "nt", "POSIX mode bits are not meaningful on Windows")
    def test_verification_receipts_use_private_permissions(self) -> None:
        self.enter_running_with_one_shot()
        receipt = verify.verify_environment(
            self.root,
            [],
            "200",
            0.1,
            test_argv=[sys.executable, "-c", "raise SystemExit(0)"],
            allow_unknown=True,
        )
        self.assertTrue(receipt["passed"])
        for name in ("environment.json", "environment.md"):
            path = self.root / ".feature-agent" / name
            self.assertEqual(stat_module.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(state.transition_state(self.root, "verified")["state"], "verified")

    def test_modified_bound_start_result_blocks_verification(self) -> None:
        start_result = self.enter_running_with_one_shot()
        result_path = self.root / start_result["result_path"]
        value = json.loads(result_path.read_text(encoding="utf-8"))
        value["argv"] = ["different-command"]
        result_path.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaises(verify.VerificationError):
            verify.verify_environment(
                self.root,
                [],
                "200",
                0.1,
                test_argv=[sys.executable, "-c", "raise SystemExit(0)"],
                allow_unknown=True,
            )

    def test_background_environment_is_verified_and_linked_to_receipt(self) -> None:
        self.approve()
        state.transition_state(self.root, "implementing")
        state.transition_state(self.root, "built")

        import socket

        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        procfile = self.root / "Procfile"
        server_command = subprocess.list2cmdline(
            [sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1"]
        )
        procfile.write_text(
            f"web: {server_command}\n",
            encoding="utf-8",
        )
        argv, cwd, source, known, index = run_command.select_command(
            self.root, "start", 0, [], False
        )
        start_result = run_command.execute_command(
            self.root,
            "start",
            argv,
            cwd=cwd,
            source=source,
            known_candidate=known,
            candidate_index=index,
            background=True,
            startup_wait=1.0,
        )
        pid = start_result["pid"]
        try:
            self.assertEqual(start_result["status"], "running")
            state.transition_state(self.root, "running")
            receipt = verify.verify_environment(
                self.root,
                [f"http://127.0.0.1:{port}/?token=do-not-persist"],
                "200",
                2.0,
            )
            self.assertTrue(receipt["passed"])
            self.assertEqual(receipt["approved_requirement_sha256"], self.digest)
            self.assertEqual(receipt["start_run"]["run_id"], start_result["run_id"])
            self.assertTrue(receipt["start_run"]["matches_approved_requirement"])
            self.assertTrue(receipt["start_run"]["process_alive"])
            self.assertNotIn("do-not-persist", json.dumps(receipt))
            markdown = (self.root / ".feature-agent" / "environment.md").read_text(
                encoding="utf-8"
            )
            self.assertNotIn("do-not-persist", markdown)
            self.assertIn("Start evidence and shutdown", markdown)
            self.assertIn(str(pid), markdown)
            self.assertEqual(state.transition_state(self.root, "verified")["state"], "verified")
        finally:
            if isinstance(pid, int):
                if os.name == "nt":
                    subprocess.run(
                        ["taskkill", "/PID", str(pid), "/T", "/F"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        check=False,
                    )
                else:
                    try:
                        os.kill(pid, signal.SIGTERM)
                        os.waitpid(pid, 0)
                    except ProcessLookupError:
                        pass
                    except ChildProcessError:
                        pass


if __name__ == "__main__":
    unittest.main()
