#!/usr/bin/env python3
"""Verify the local-only S4 PPT runtime before a Codex or Harness turn."""

from __future__ import annotations

import argparse
import importlib
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / ".agents" / "skills" / "ppt-master"
REQUIRED_MODULES = {
    "pptx": "python-pptx",
    "xlsxwriter": "XlsxWriter",
    "pathops": "skia-pathops",
    "uharfbuzz": "uharfbuzz",
}
BLOCKED_PREFIXES = (
    "IMAGE_", "GEMINI_", "OPENAI_", "MINIMAX_", "STABILITY_", "BFL_", "IDEOGRAM_",
    "QWEN_", "DASHSCOPE_", "ZHIPU_", "BIGMODEL_", "VOLCENGINE_", "ARK_", "MODELSCOPE_",
    "SILICONFLOW_", "FAL_", "REPLICATE_", "OPENROUTER_", "ELEVENLABS_", "COSYVOICE_",
    "PEXELS_", "PIXABAY_", "GOOGLE_API_KEY",
)


def blocked_environment() -> dict[str, str]:
    return {key: "" for key in os.environ if key.startswith(BLOCKED_PREFIXES)}


def verify() -> list[str]:
    errors: list[str] = []
    for relative in ("SKILL.md", "scripts/attribution_guard.py", "scripts/svg_to_pptx.py"):
        if not (SKILL / relative).is_file():
            errors.append(f"missing skill file: {relative}")
    for module, distribution in REQUIRED_MODULES.items():
        try:
            importlib.import_module(module)
        except Exception as exc:  # pragma: no cover - platform import messages vary
            errors.append(f"{distribution} unavailable: {exc}")
    credentials = sorted(key for key in os.environ if key.startswith(BLOCKED_PREFIXES) and os.environ.get(key))
    if credentials:
        errors.append("provider credentials must be removed before local-only S4 execution: " + ", ".join(credentials))
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--print-env", action="store_true")
    args = parser.parse_args()
    errors = verify()
    if errors:
        print("S4_PPT_PREFLIGHT_FAILED")
        print("\n".join(errors))
        return 1
    if args.print_env:
        for key, value in sorted(blocked_environment().items()):
            print(f"{key}={value}")
    print("S4_PPT_PREFLIGHT_PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
