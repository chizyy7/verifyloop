"""Probe the configured provider with a tiny, cheap request.

This is a thin wrapper around :func:`verifyloop.model_providers.diagnostics.
diagnose_provider`, which is also used by ``verifyloop provider-check``. It checks
reachability, model presence, a real generation, and response parsing.

Example (PowerShell)::

    $env:MODEL_PROVIDER="ollama"
    $env:MODEL_NAME="llama3.2:3b"
    $env:MODEL_BASE_URL="http://localhost:11434"
    python scripts/probe_provider.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from verifyloop.config import load_default_config  # noqa: E402
from verifyloop.model_providers import build_provider  # noqa: E402
from verifyloop.model_providers.base import ProviderError  # noqa: E402
from verifyloop.model_providers.diagnostics import diagnose_provider  # noqa: E402


def main() -> int:
    config = load_default_config(use_env=True)
    print(f"provider={config.provider.provider} model={config.provider.model}")
    print(
        f"base_url={config.provider.base_url} "
        f"api_key_present={bool(config.provider.api_key)}"
    )
    if config.provider.provider == "mock":
        print("mock provider selected; set MODEL_PROVIDER to probe a real model")
        return 0
    try:
        provider = build_provider(config.provider)
    except ProviderError as exc:
        print(f"ERROR: {exc}")
        return 1

    report = diagnose_provider(provider)
    print(report.render())
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
