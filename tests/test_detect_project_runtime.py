from __future__ import annotations

import json
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

import detect_project  # noqa: E402


class DetectProjectTests(unittest.TestCase):
    def project(self) -> tuple[tempfile.TemporaryDirectory[str], Path]:
        temporary = tempfile.TemporaryDirectory()
        return temporary, Path(temporary.name).resolve()

    def test_empty_directory_has_no_guessed_commands(self) -> None:
        temporary, root = self.project()
        self.addCleanup(temporary.cleanup)
        result = detect_project.detect_project(root)
        self.assertEqual(result["detected_types"], [])
        self.assertTrue(all(not values for values in result["commands"].values()))

    def test_node_commands_come_from_lockfile_and_scripts(self) -> None:
        temporary, root = self.project()
        self.addCleanup(temporary.cleanup)
        (root / "package.json").write_text(
            json.dumps(
                {
                    "packageManager": "pnpm@10.0.0",
                    "scripts": {"build": "vite build", "dev": "vite", "lint": "eslint ."},
                }
            ),
            encoding="utf-8",
        )
        (root / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")
        result = detect_project.detect_project(root)
        self.assertIn("node", [item["type"] for item in result["detected_types"]])
        self.assertEqual(result["commands"]["install"][0]["argv"], ["pnpm", "install", "--frozen-lockfile"])
        self.assertEqual(result["commands"]["build"][0]["argv"], ["pnpm", "run", "build"])
        self.assertEqual(result["commands"]["start"][0]["argv"], ["pnpm", "run", "dev"])
        self.assertEqual(result["commands"]["test"], [])
        all_argv = [item["argv"] for phase in result["commands"].values() for item in phase]
        self.assertNotIn(["pnpm", "run", "lint"], all_argv)

    def test_python_candidates_require_corresponding_configuration(self) -> None:
        temporary, root = self.project()
        self.addCleanup(temporary.cleanup)
        (root / "pyproject.toml").write_text(
            "[build-system]\nrequires = ['setuptools']\n\n[tool.pytest.ini_options]\naddopts = '-q'\n",
            encoding="utf-8",
        )
        (root / "requirements-dev.txt").write_text("pytest==9.0.0\n", encoding="utf-8")
        result = detect_project.detect_project(root)
        self.assertIn(
            [detect_project.PYTHON_EXECUTABLE, "-m", "pip", "install", "-r", "requirements-dev.txt"],
            [item["argv"] for item in result["commands"]["install"]],
        )
        self.assertEqual(
            result["commands"]["build"][0]["argv"],
            [detect_project.PYTHON_EXECUTABLE, "-m", "build"],
        )
        self.assertEqual(
            result["commands"]["test"][0]["argv"],
            [detect_project.PYTHON_EXECUTABLE, "-m", "pytest"],
        )
        self.assertEqual(result["commands"]["start"], [])

    def test_procfile_shell_interpreter_requires_explicit_review(self) -> None:
        temporary, root = self.project()
        self.addCleanup(temporary.cleanup)
        (root / "requirements.txt").write_text("flask==3.1.0\n", encoding="utf-8")
        (root / "Procfile").write_text(
            "web: /bin/sh -c 'python3 app.py && touch /tmp/marker'\n",
            encoding="utf-8",
        )
        result = detect_project.detect_project(root)
        self.assertEqual(result["commands"]["start"], [])
        self.assertTrue(
            any("requires shell parsing" in warning for warning in result["warnings"])
        )

        (root / "Procfile").write_text(
            f"web: {detect_project.PYTHON_EXECUTABLE} app.py\n",
            encoding="utf-8",
        )
        result = detect_project.detect_project(root)
        self.assertEqual(
            result["commands"]["start"][0]["argv"],
            [detect_project.PYTHON_EXECUTABLE, "app.py"],
        )

    def test_make_and_docker_candidates_reference_existing_files_and_targets(self) -> None:
        temporary, root = self.project()
        self.addCleanup(temporary.cleanup)
        (root / "Makefile").write_text(
            ".PHONY: build test serve\nbuild:\n\t@true\ntest:\n\t@true\nserve:\n\t@true\n",
            encoding="utf-8",
        )
        (root / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
        result = detect_project.detect_project(root)
        types = [item["type"] for item in result["detected_types"]]
        self.assertIn("make", types)
        self.assertIn("docker", types)
        build_sources = {item["source"] for item in result["commands"]["build"]}
        self.assertIn("Makefile:target:build", build_sources)
        self.assertIn("compose.yaml", build_sources)
        self.assertIn(
            ["docker", "compose", "-f", "compose.yaml", "up", "--detach"],
            [item["argv"] for item in result["commands"]["start"]],
        )

    def test_rust_go_and_java_are_recognized_from_manifests(self) -> None:
        temporary, root = self.project()
        self.addCleanup(temporary.cleanup)
        (root / "Cargo.toml").write_text("[package]\nname='demo'\nversion='0.1.0'\n", encoding="utf-8")
        (root / "go.mod").write_text("module example.test/demo\n\ngo 1.23\n", encoding="utf-8")
        (root / "pom.xml").write_text("<project></project>\n", encoding="utf-8")
        result = detect_project.detect_project(root)
        types = {item["type"] for item in result["detected_types"]}
        self.assertTrue({"rust", "go", "java"}.issubset(types))
        build_commands = [item["argv"] for item in result["commands"]["build"]]
        self.assertIn(["cargo", "build"], build_commands)
        self.assertIn(["go", "build", "./..."], build_commands)
        self.assertIn(["mvn", "package"], build_commands)


if __name__ == "__main__":
    unittest.main()
