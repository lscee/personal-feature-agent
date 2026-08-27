#!/usr/bin/env python3
"""Build a reproducible standalone plugin archive for release attachments."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "personal-feature-agent"
DIST = ROOT / "dist"


def main() -> int:
    manifest = json.loads((PLUGIN / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
    version = manifest["version"]
    DIST.mkdir(exist_ok=True)
    target = DIST / f"personal-feature-agent-{version}.zip"
    files = sorted(path for path in PLUGIN.rglob("*") if path.is_file() and "__pycache__" not in path.parts)
    archive_files = [(path, Path("personal-feature-agent") / path.relative_to(PLUGIN)) for path in files]
    archive_files.append((ROOT / "LICENSE", Path("personal-feature-agent") / "LICENSE"))
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path, relative in sorted(archive_files, key=lambda item: item[1].as_posix()):
            info = zipfile.ZipInfo(relative.as_posix(), date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes())
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
