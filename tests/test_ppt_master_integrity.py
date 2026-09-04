from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / ".agents" / "skills" / "ppt-master"
METADATA_PATH = ROOT / ".agents" / "skills" / "ppt-master.upstream.json"
LOCK_PATH = ROOT / "tools" / "s4_ppt_requirements.lock"


def tree_digest(root: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    files = 0
    for path in sorted(
        path for path in root.rglob("*")
        if path.is_file() and path.name != ".DS_Store" and "__pycache__" not in path.parts
    ):
        relative = path.relative_to(root).as_posix()
        digest.update(f"{relative}\0".encode("utf-8"))
        digest.update(hashlib.sha256(path.read_bytes()).hexdigest().encode("ascii"))
        digest.update(b"\n")
        files += 1
    return digest.hexdigest(), files


class PptMasterIntegrityTests(unittest.TestCase):
    def test_tree_digest_ignores_python_runtime_cache(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "module.py").write_text("value = 1\n", encoding="utf-8")
            expected = tree_digest(root)
            cache = root / "__pycache__"
            cache.mkdir()
            (cache / "module.cpython-312.pyc").write_bytes(b"runtime cache")
            self.assertEqual(tree_digest(root), expected)

    def test_pinned_metadata_and_complete_tree(self) -> None:
        metadata = json.loads(METADATA_PATH.read_text(encoding="utf-8"))
        self.assertEqual(metadata["repository"], "https://github.com/hugohe3/ppt-master")
        self.assertEqual(metadata["tag"], "v4.7.0")
        self.assertEqual(metadata["commit"], "e8323bfaee249cffe1301ec40fca5875eb544d46")
        self.assertEqual(metadata["license"], "MIT")
        self.assertRegex(metadata["release_zip_sha256"], r"^[0-9a-f]{64}$")

        expected_paths = (
            "SKILL.md",
            "LICENSE",
            "SPONSORS.md",
            "SPONSORS_CN.md",
            "requirements.txt",
            "workflows/routing.md",
            "scripts/attribution_guard.py",
            "scripts/pptx_delivery_check.py",
            "templates/styles/styles_index.json",
        )
        for relative in expected_paths:
            self.assertTrue((SKILL_ROOT / relative).is_file(), relative)

        skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn('version: "4.7.0"', skill)
        self.assertIn('license: "MIT"', skill)
        self.assertIn("official_repository: \"https://github.com/hugohe3/ppt-master\"", skill)

        actual_digest, actual_count = tree_digest(SKILL_ROOT)
        self.assertEqual(actual_digest, metadata["tree_digest"]["value"])
        self.assertEqual(actual_count, metadata["tree_digest"]["file_count"])

    def test_upstream_attribution_guard_passes_offline(self) -> None:
        result = subprocess.run(
            [sys.executable, "scripts/attribution_guard.py"],
            cwd=SKILL_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_runtime_dependency_lock_is_exact_and_project_owned(self) -> None:
        lock = LOCK_PATH.read_text(encoding="utf-8")
        self.assertIn("python-pptx==1.0.2", lock)
        self.assertIn("XlsxWriter==3.2.9", lock)
        self.assertIn("skia-pathops==0.9.2", lock)
        self.assertNotIn(">=", lock)

    def test_local_preflight_blocks_image_search_credentials(self) -> None:
        source = (ROOT / "analysis_product" / "s4_ppt_preflight.py").read_text(encoding="utf-8")
        for prefix in ("PEXELS_", "PIXABAY_", "GOOGLE_API_KEY"):
            self.assertIn(prefix, source)


if __name__ == "__main__":
    unittest.main()
