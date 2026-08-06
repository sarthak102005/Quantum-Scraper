"""
shared/utils/config.py

Loads configs/config.yaml into a typed dataclass hierarchy.
All configuration values must come from here — nothing is hardcoded.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import yaml
from dotenv import load_dotenv

load_dotenv()

# Locate the project root (two levels up from this file: shared/utils/ → root)
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_CONFIG_PATH = _PROJECT_ROOT / "configs" / "config.yaml"


@dataclass
class ConcurrencyConfig:
    max_requests_per_domain: int = 3
    global_max_requests: int = 10
    browser_instance_limit: int = 2


@dataclass
class DelaysConfig:
    min_ms: int = 500
    max_ms: int = 2000
    jitter: bool = True


@dataclass
class RetriesConfig:
    max_attempts: int = 3
    backoff_factor: float = 2.0


@dataclass
class BrowserConfig:
    headless: bool = True
    timeout_ms: int = 30_000
    wait_for_selector: str | None = None


@dataclass
class CacheConfig:
    enabled: bool = True
    ttl_seconds: int = 3600
    max_size_mb: int = 100


@dataclass
class OutputConfig:
    formats: list[str] = field(default_factory=lambda: ["csv", "json", "sqlite"])
    directory: str = "outputs/"
    streaming: bool = True


@dataclass
class LLMConfig:
    primary: Literal["gemini", "groq", "openrouter"] = "gemini"
    fallback: list[str] = field(default_factory=lambda: ["groq", "openrouter"])
    extraction_fallback_enabled: bool = False
    gemini_model: str = "gemini-2.5-flash"
    groq_model: str = "llama-3.3-70b-versatile"
    openrouter_model: str = "qwen/qwen3-8b"

    # API keys sourced from environment
    @property
    def google_api_key(self) -> str:
        return os.environ.get("GOOGLE_API_KEY", "")

    @property
    def groq_api_key(self) -> str:
        return os.environ.get("GROQ_API_KEY", "")

    @property
    def openrouter_api_key(self) -> str:
        return os.environ.get("OPENROUTER_API_KEY", "")


@dataclass
class ProxiesConfig:
    enabled: bool = False
    pool: list[str] = field(default_factory=list)
    rotation: Literal["random", "round_robin"] = "random"


@dataclass
class KnowledgeConfig:
    db_path: str = "outputs/knowledge.db"
    profile_ttl_days: int = 7


@dataclass
class ClassificationConfig:
    threshold: int = 60


@dataclass
class LoggingConfig:
    level: str = "INFO"
    format: Literal["json", "text"] = "json"
    output: str = "logs/crawl.log"


@dataclass
class CrawlScopeConfig:
    policy: Literal[
        "seed_path",
        "same_locale",
        "same_country",
        "entire_domain",
        "cross_locale",
        "cross_domain",
    ] = "seed_path"


@dataclass
class Config:
    concurrency: ConcurrencyConfig = field(default_factory=ConcurrencyConfig)
    delays: DelaysConfig = field(default_factory=DelaysConfig)
    retries: RetriesConfig = field(default_factory=RetriesConfig)
    browser: BrowserConfig = field(default_factory=BrowserConfig)
    cache: CacheConfig = field(default_factory=CacheConfig)
    output: OutputConfig = field(default_factory=OutputConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    proxies: ProxiesConfig = field(default_factory=ProxiesConfig)
    knowledge: KnowledgeConfig = field(default_factory=KnowledgeConfig)
    classification: ClassificationConfig = field(default_factory=ClassificationConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    crawl_scope: CrawlScopeConfig = field(default_factory=CrawlScopeConfig)

    @property
    def project_root(self) -> Path:
        return _PROJECT_ROOT


def _load_section(cls: type, data: dict) -> object:
    """Recursively instantiate a dataclass from a dict, ignoring unknown keys."""
    import dataclasses

    if not dataclasses.is_dataclass(cls):
        return data
    known_fields = {f.name for f in dataclasses.fields(cls)}
    filtered = {k: v for k, v in data.items() if k in known_fields}
    return cls(**filtered)


def load_config(path: Path | str | None = None) -> Config:
    """Load and parse config.yaml into a typed Config instance.

    Args:
        path: Optional override for config file path.

    Returns:
        Populated Config dataclass.

    Raises:
        FileNotFoundError: If the config file does not exist.
        ValueError: If the config file is malformed.
    """
    config_path = Path(path) if path else _DEFAULT_CONFIG_PATH

    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with config_path.open("r", encoding="utf-8") as fh:
        raw: dict = yaml.safe_load(fh) or {}

    return Config(
        concurrency=_load_section(ConcurrencyConfig, raw.get("concurrency", {})),
        delays=_load_section(DelaysConfig, raw.get("delays", {})),
        retries=_load_section(RetriesConfig, raw.get("retries", {})),
        browser=_load_section(BrowserConfig, raw.get("browser", {})),
        cache=_load_section(CacheConfig, raw.get("cache", {})),
        output=_load_section(OutputConfig, raw.get("output", {})),
        llm=_load_section(LLMConfig, raw.get("llm", {})),
        proxies=_load_section(ProxiesConfig, raw.get("proxies", {})),
        knowledge=_load_section(KnowledgeConfig, raw.get("knowledge", {})),
        classification=_load_section(ClassificationConfig, raw.get("classification", {})),
        logging=_load_section(LoggingConfig, raw.get("logging", {})),
        crawl_scope=_load_section(CrawlScopeConfig, raw.get("crawl_scope", {})),
    )


# Module-level singleton — import this everywhere
_config_instance: Config | None = None


def get_config() -> Config:
    """Return the module-level singleton Config, loading it on first call."""
    global _config_instance
    if _config_instance is None:
        _config_instance = load_config()
    return _config_instance
