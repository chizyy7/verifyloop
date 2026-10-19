"""Configuration loading, validation, and secret redaction.

Design notes
------------
* Credentials are never stored in YAML. Configuration references the *name* of an
  environment variable (``api_key_env``); the value is resolved at load time and
  excluded from every serialized representation.
* Environment variables override YAML so a run can be pointed at a different model
  without editing a committed file.
* ``.env`` files are parsed by a tiny local loader rather than ``python-dotenv`` to
  keep the dependency surface small. Existing environment variables always win.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Literal, Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ProviderName = Literal["mock", "ollama", "openai_compatible"]
StrategyName = Literal["oneshot", "blind_retry", "evidence_guided", "concise_feedback"]

STRATEGY_NAMES: tuple[str, ...] = (
    "oneshot",
    "blind_retry",
    "evidence_guided",
    "concise_feedback",
)

REDACTED = "***redacted***"


class ProviderConfig(BaseModel):
    """Settings for the model provider adapter."""

    model_config = ConfigDict(extra="forbid")

    provider: ProviderName = "mock"
    model: str = "mock-scripted"
    base_url: str = "http://localhost:11434"
    api_key_env: str = "MODEL_API_KEY"
    request_timeout_seconds: float = Field(default=120.0, gt=0, le=1800)
    max_output_tokens: int = Field(default=900, gt=0, le=32768)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    seed: Optional[int] = Field(default=None, ge=0)

    # Resolved at load time; never serialized.
    _api_key: Optional[str] = None

    @property
    def api_key(self) -> Optional[str]:
        return self._api_key

    def with_api_key(self, value: Optional[str]) -> "ProviderConfig":
        clone = self.model_copy()
        object.__setattr__(clone, "_api_key", value)
        return clone

    def describe(self) -> Dict[str, Any]:
        """Safe-to-log summary. Contains no secret material."""
        return {
            "provider": self.provider,
            "model": self.model,
            "base_url": self.base_url,
            "api_key_env": self.api_key_env,
            "api_key_present": bool(self._api_key),
            "request_timeout_seconds": self.request_timeout_seconds,
            "max_output_tokens": self.max_output_tokens,
            "temperature": self.temperature,
            "seed": self.seed,
        }

    @model_validator(mode="after")
    def _validate_requirements(self) -> "ProviderConfig":
        if self.provider == "ollama" and not self.base_url:
            raise ValueError("ollama provider requires base_url")
        if self.provider == "openai_compatible" and not self.base_url:
            raise ValueError("openai_compatible provider requires base_url")
        return self


class BudgetConfig(BaseModel):
    """Hard resource ceilings. Every one of these is enforced by the controller."""

    model_config = ConfigDict(extra="forbid")

    max_attempts: int = Field(default=3, ge=1, le=10)
    max_model_calls: int = Field(default=12, ge=1, le=200)
    max_total_tokens: int = Field(default=60_000, ge=1_000)
    max_wall_clock_seconds: float = Field(default=900.0, gt=0)
    max_patch_bytes: int = Field(default=24_000, gt=0)
    max_output_chars: int = Field(default=6_000, gt=0)
    test_timeout_seconds: float = Field(default=120.0, gt=0)


class BenchmarkConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    root: str = "benchmarks/synthetic"
    version: str = "v1"
    # Empty list means "all tasks in the manifest".
    task_ids: list[str] = Field(default_factory=list)
    # Repository-relative globs that a patch may never touch.
    protected_paths: list[str] = Field(
        default_factory=lambda: [
            "**/test_*.py",
            "**/*_test.py",
            "**/tests/**",
            "**/eval_tests/**",
            "**/manifest.json",
            "**/reference/**",
            "**/task.json",
        ]
    )


class ExecutionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Only these executables may be invoked by the runner.
    allowed_commands: list[str] = Field(
        default_factory=lambda: ["python", "python3", "py", "pytest"]
    )
    workspace_root: Optional[str] = None
    keep_workspaces: bool = False


class ExperimentConfig(BaseModel):
    """Top-level experiment specification."""

    model_config = ConfigDict(extra="forbid")

    name: str = "default"
    benchmark: BenchmarkConfig = Field(default_factory=BenchmarkConfig)
    provider: ProviderConfig = Field(default_factory=ProviderConfig)
    budgets: BudgetConfig = Field(default_factory=BudgetConfig)
    execution: ExecutionConfig = Field(default_factory=ExecutionConfig)
    strategies: list[StrategyName] = Field(
        default_factory=lambda: ["oneshot", "blind_retry", "evidence_guided"]
    )
    trials: int = Field(default=1, ge=1, le=20)
    # Order in which tasks are attempted. "fixed" uses manifest order.
    task_order: Literal["fixed", "shuffled"] = "fixed"
    # Patch exchange format requested from the model.
    patch_format: Literal["diff", "edit_json"] = "diff"
    output_dir: str = "outputs"
    notes: str = ""

    @field_validator("strategies")
    @classmethod
    def _dedupe_strategies(cls, value: list[str]) -> list[str]:
        seen: list[str] = []
        for item in value:
            if item not in STRATEGY_NAMES:
                raise ValueError(f"unknown strategy: {item}")
            if item not in seen:
                seen.append(item)
        if not seen:
            raise ValueError("at least one strategy is required")
        return seen

    def redacted_dict(self) -> Dict[str, Any]:
        data = self.model_dump(mode="json")
        data["provider"] = self.provider.describe()
        return data


# --------------------------------------------------------------------------
# .env loading
# --------------------------------------------------------------------------


def parse_dotenv(text: str) -> Dict[str, str]:
    """Parse a minimal ``KEY=VALUE`` file. Comments and blanks are ignored."""
    values: Dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :]
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def load_dotenv(path: Path, override: bool = False) -> Dict[str, str]:
    """Load ``path`` into ``os.environ`` without overwriting by default."""
    if not path.is_file():
        return {}
    values = parse_dotenv(path.read_text(encoding="utf-8"))
    for key, value in values.items():
        if override or key not in os.environ:
            os.environ[key] = value
    return values


_ENV_MAP: Dict[str, tuple[str, ...]] = {
    "MODEL_PROVIDER": ("provider", "provider"),
    "MODEL_NAME": ("provider", "model"),
    "MODEL_BASE_URL": ("provider", "base_url"),
    "MODEL_API_KEY_ENV": ("provider", "api_key_env"),
    "REQUEST_TIMEOUT_SECONDS": ("provider", "request_timeout_seconds"),
    "MAX_OUTPUT_TOKENS": ("provider", "max_output_tokens"),
    "TEMPERATURE": ("provider", "temperature"),
    "MAX_MODEL_CALLS": ("budgets", "max_model_calls"),
    "MAX_TOTAL_TOKENS": ("budgets", "max_total_tokens"),
}


def _coerce(raw: str, current: Any) -> Any:
    if isinstance(current, bool):
        return raw.strip().lower() in {"1", "true", "yes", "on"}
    if isinstance(current, int):
        return int(float(raw))
    if isinstance(current, float):
        return float(raw)
    return raw


def apply_env_overrides(data: Dict[str, Any], environ: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Apply ``MODEL_*``-style environment overrides to a raw config dict."""
    env = os.environ if environ is None else environ
    for env_name, (section, key) in _ENV_MAP.items():
        raw = env.get(env_name)
        if raw is None or raw == "":
            continue
        section_data = data.setdefault(section, {})
        if not isinstance(section_data, dict):
            continue
        section_data[key] = _coerce(raw, section_data.get(key))
    return data


def resolve_api_key(provider: ProviderConfig, environ: Optional[Dict[str, str]] = None) -> Optional[str]:
    """Look up the secret named by ``api_key_env``. Never raises, never logs."""
    env = os.environ if environ is None else environ
    value = env.get(provider.api_key_env)
    return value or None


def load_config(path: Optional[str | Path] = None, *, use_env: bool = True) -> ExperimentConfig:
    """Load configuration from YAML plus environment overrides.

    Raises ``FileNotFoundError`` if an explicit path does not exist and
    ``pydantic.ValidationError`` if the merged configuration is invalid.
    """
    raw: Dict[str, Any] = {}
    if path is not None:
        config_path = Path(path)
        if not config_path.is_file():
            raise FileNotFoundError(f"configuration file not found: {config_path}")
        loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        if loaded is None:
            loaded = {}
        if not isinstance(loaded, dict):
            raise ValueError(f"configuration root must be a mapping: {config_path}")
        raw = loaded

    if use_env:
        raw = apply_env_overrides(raw)

    config = ExperimentConfig.model_validate(raw)
    if use_env:
        config = config.model_copy(
            update={"provider": config.provider.with_api_key(resolve_api_key(config.provider))}
        )
    return config


def config_search_paths(explicit: Optional[str] = None) -> list[Path]:
    """Candidate config paths, in priority order."""
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit))
        return candidates
    here = Path(__file__).resolve()
    repo_root = here.parents[2]
    candidates.append(Path.cwd() / "config" / "default.yaml")
    candidates.append(repo_root / "config" / "default.yaml")
    return candidates


def load_default_config(explicit: Optional[str] = None, *, use_env: bool = True) -> ExperimentConfig:
    """Load the first existing candidate configuration, else pure defaults."""
    for candidate in config_search_paths(explicit):
        if candidate.is_file():
            return load_config(candidate, use_env=use_env)
    if explicit:
        raise FileNotFoundError(f"configuration file not found: {explicit}")
    return load_config(None, use_env=use_env)
