from __future__ import annotations

import json
import os
import stat as stat_module
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

import state  # noqa: E402
import run_command  # noqa: E402


class StateRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        state.init_state(self.root)

    def tearDown(self) -> None:
        self.temp.cleanup()

    @property
    def requirement(self) -> Path:
        return self.root / ".feature-agent" / "requirement.md"

    def write_requirement(self, text: str = "# Feature\n\nShip an example.\n") -> str:
        self.requirement.parent.mkdir(parents=True, exist_ok=True)
        self.requirement.write_text(text, encoding="utf-8")
        return state.sha256_file(self.requirement)

    def prepare_approved(self) -> str:
        digest = self.write_requirement()
        state.transition_state(self.root, "awaiting_approval")
        state.approve_requirement(self.root, digest)
        return digest

    def test_awaiting_approval_requires_nonempty_requirement_and_shows_hash(self) -> None:
        with self.assertRaises(state.StateError):
            state.transition_state(self.root, "awaiting_approval")
        digest = self.write_requirement()
        data = state.transition_state(self.root, "awaiting_approval")
        shown = state.state_for_display(self.root, data)
        self.assertEqual(shown["current_requirement"]["sha256"], digest)
        self.assertGreater(shown["current_requirement"]["size_bytes"], 0)
        self.assertIsNone(shown["requirement_integrity"]["approved_sha256"])

    def test_approve_requires_exact_user_seen_hash(self) -> None:
        digest = self.write_requirement()
        state.transition_state(self.root, "awaiting_approval")
        with self.assertRaises(state.StateError):
            state.approve_requirement(self.root, "0" * 64)
        self.assertEqual(state.load_state(self.root)["state"], "awaiting_approval")
        approved = state.approve_requirement(self.root, digest.upper())
        self.assertEqual(approved["state"], "approved")
        self.assertEqual(approved["requirement"]["sha256"], digest)

    def test_illegal_jump_and_silent_approval_are_rejected(self) -> None:
        self.write_requirement()
        with self.assertRaises(state.StateError):
            state.transition_state(self.root, "implementing")
        state.transition_state(self.root, "awaiting_approval")
        with self.assertRaises(state.StateError):
            state.transition_state(self.root, "approved")

    def test_copied_state_is_rejected_in_a_different_project_root(self) -> None:
        copied_root = self.root / "copied-project"
        copied_agent_dir = copied_root / ".feature-agent"
        copied_agent_dir.mkdir(parents=True)
        copied_state = json.loads((self.root / ".feature-agent" / "state.json").read_text())
        (copied_agent_dir / "state.json").write_text(json.dumps(copied_state), encoding="utf-8")
        with self.assertRaises(state.StateError):
            state.load_state(copied_root)

    def test_feature_agent_directory_symlink_escape_is_rejected(self) -> None:
        root = self.root / "symlink-project"
        outside = self.root / "outside-workspace"
        root.mkdir()
        outside.mkdir()
        link = root / ".feature-agent"
        try:
            link.symlink_to(outside, target_is_directory=True)
        except (NotImplementedError, OSError) as exc:
            self.skipTest(f"symbolic links are unavailable: {exc}")
        with self.assertRaises(state.StateError):
            state.init_state(root)
        self.assertEqual(list(outside.iterdir()), [])

    @unittest.skipIf(os.name == "nt", "POSIX mode bits are not meaningful on Windows")
    def test_state_workspace_uses_private_permissions(self) -> None:
        agent_dir = self.root / ".feature-agent"
        state_file = agent_dir / "state.json"
        self.assertEqual(stat_module.S_IMODE(agent_dir.stat().st_mode), 0o700)
        self.assertEqual(stat_module.S_IMODE(state_file.stat().st_mode), 0o600)

        self.write_requirement()
        state.transition_state(self.root, "awaiting_approval")
        self.assertEqual(stat_module.S_IMODE(state_file.stat().st_mode), 0o600)

    def test_tampered_requirement_blocks_post_approval_transition(self) -> None:
        self.prepare_approved()
        self.requirement.write_text("changed after approval", encoding="utf-8")
        with self.assertRaises(state.StateError):
            state.transition_state(self.root, "implementing")
        shown = state.state_for_display(self.root, state.load_state(self.root))
        self.assertFalse(shown["requirement_integrity"]["integrity"])

    def test_revision_reopens_only_before_implementation(self) -> None:
        self.prepare_approved()
        reopened = state.revise_requirement(self.root)
        self.assertEqual(reopened["state"], "awaiting_approval")
        self.assertIsNone(reopened["requirement"])
        digest = self.write_requirement("# Revised\n")
        state.approve_requirement(self.root, digest)
        state.transition_state(self.root, "implementing")
        with self.assertRaises(state.StateError):
            state.revise_requirement(self.root)

    def test_built_requires_current_detected_build_and_test_evidence(self) -> None:
        self.prepare_approved()
        (self.root / "Makefile").write_text(
            ".PHONY: build test\nbuild:\n\t@true\ntest:\n\t@true\n",
            encoding="utf-8",
        )
        state.transition_state(self.root, "implementing")
        with self.assertRaises(state.StateError):
            state.transition_state(self.root, "built")
        for phase in ("build", "test"):
            run_command.execute_command(
                self.root,
                phase,
                [sys.executable, "-c", "raise SystemExit(0)"],
                known_candidate=True,
            )
        built = state.transition_state(self.root, "built")
        self.assertEqual(built["build_evidence"]["build"]["status"], "passed")
        self.assertEqual(built["build_evidence"]["test"]["status"], "passed")

    def test_latest_failed_phase_run_blocks_built(self) -> None:
        self.prepare_approved()
        state.transition_state(self.root, "implementing")
        run_command.execute_command(
            self.root,
            "build",
            [sys.executable, "-c", "raise SystemExit(0)"],
            known_candidate=True,
        )
        run_command.execute_command(
            self.root,
            "build",
            [sys.executable, "-c", "raise SystemExit(7)"],
            known_candidate=True,
        )
        with self.assertRaises(state.StateError):
            state.transition_state(self.root, "built")

    def test_running_requires_current_start_evidence(self) -> None:
        self.prepare_approved()
        state.transition_state(self.root, "implementing")
        state.transition_state(self.root, "built")
        with self.assertRaises(state.StateError):
            state.transition_state(self.root, "running")

    def test_verified_rejects_minimal_forged_receipt(self) -> None:
        digest = self.prepare_approved()
        state.transition_state(self.root, "implementing")
        state.transition_state(self.root, "built")
        run_command.execute_command(
            self.root,
            "start",
            [sys.executable, "-c", "raise SystemExit(0)"],
            known_candidate=True,
        )
        state.transition_state(self.root, "running")
        with self.assertRaises(state.StateError):
            state.transition_state(self.root, "verified")

        receipt_path = self.root / ".feature-agent" / "environment.json"
        receipt_path.write_text(
            json.dumps(
                {
                    "passed": True,
                    "project_root": str(self.root),
                    "approved_requirement_sha256": "0" * 64,
                    "verified_at": "2026-01-01T00:00:00Z",
                }
            ),
            encoding="utf-8",
        )
        with self.assertRaises(state.StateError):
            state.transition_state(self.root, "verified")
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        receipt["approved_requirement_sha256"] = digest
        receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
        with self.assertRaises(state.StateError):
            state.transition_state(self.root, "verified")


if __name__ == "__main__":
    unittest.main()
