"""AgroAdvisor CLI -- end-to-end demo of the multi-agent advisory pipeline.

Usage:
    uv run python cli.py --photo sample_data/sample_leaf.jpg --location "Ludhiana, Punjab, India" --crop wheat [--pincode 141001]
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()  # must run before importing agents.* -- they read env vars at import time

from observability import flush_tracing, setup_langsmith_tracing

setup_langsmith_tracing()  # no-op unless LANGSMITH_API_KEY is set

from advisor import run_advisory
from languages import resolve_language
from security.guardrails import GuardrailError


def _print_event(author: str, text: str) -> None:
    print(f"[{author}] {text}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="AgroAdvisor multi-agent CLI")
    parser.add_argument("--photo", required=True, type=Path, help="Path to a crop photo")
    parser.add_argument("--location", required=True, help="e.g. 'Ludhiana, Punjab, India'")
    parser.add_argument("--crop", required=True, help="e.g. 'wheat'")
    parser.add_argument(
        "--pincode", help="Optional 6-digit pincode, to link the farmer's nearest KVK"
    )
    parser.add_argument(
        "--language",
        default="English",
        help="Output language for the advisory, e.g. 'Hindi', 'Punjabi', 'Tamil' (default: English)",
    )
    args = parser.parse_args()

    language = resolve_language(args.language).name

    try:
        result = asyncio.run(
            run_advisory(
                args.photo, args.location, args.crop, args.pincode, language, on_event=_print_event
            )
        )
    except GuardrailError as exc:
        raise SystemExit(f"Rejected input: {exc}")
    finally:
        flush_tracing()

    print("=" * 60)
    print("FINAL ADVISORY")
    print("=" * 60)
    print(result.final)


if __name__ == "__main__":
    main()
