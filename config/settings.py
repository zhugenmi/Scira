"""
Scira Configuration Module

Multi-model support for OpenAI, Anthropic Claude, and other providers.
Supports custom base URLs for API compatibility.
"""

import os
from enum import Enum
from typing import Optional, Dict, Any, Union
from pydantic import BaseModel, Field
from dotenv import load_dotenv

load_dotenv()


class ModelProvider(str, Enum):
    """Supported LLM providers."""
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    CUSTOM = "custom"  # Custom OpenAI-compatible API


class ModelConfig(BaseModel):
    """Model configuration."""
    provider: ModelProvider = Field(default=ModelProvider.OPENAI, description="LLM provider")
    model_name: str = Field(default="gpt-4o", description="Model name")
    temperature: float = Field(default=0.7, ge=0.0, le=2.0, description="Sampling temperature")
    max_tokens: Optional[int] = Field(default=None, description="Max tokens to generate")

    # API 配置
    api_key: Optional[str] = Field(default=None, description="API key (optional, uses env if not provided)")
    base_url: Optional[str] = Field(default=None, description="Custom API base URL (for compatible APIs)")
    api_version: Optional[str] = Field(default=None, description="API version (for Azure/OpenAI)")

    # 高级配置
    timeout: int = Field(default=120, description="Request timeout in seconds")
    max_retries: int = Field(default=3, description="Max retry attempts")


class SciraConfig(BaseModel):
    """Scira global configuration."""

    # Model settings
    model: ModelConfig = Field(default_factory=ModelConfig)

    # LangSmith tracing (optional)
    langsmith_tracing: bool = Field(default=False, description="Enable LangSmith tracing")
    langsmith_api_key: Optional[str] = Field(default=None, description="LangSmith API key")
    langsmith_project: str = Field(default="scira-research-agent", description="LangSmith project name")

    # Paths
    data_dir: str = Field(default="data", description="Data directory")
    output_dir: str = Field(default="data/outputs", description="Output directory")
    cache_dir: str = Field(default="data/cache", description="Cache directory")

    # Behavior
    auto_approve: bool = Field(default=False, description="Skip human approval steps")
    max_literature_count: int = Field(default=20, description="Max literature papers to process")

    @classmethod
    def from_env(cls) -> "SciraConfig":
        """Load configuration from environment variables."""

        # Determine provider
        provider_str = os.getenv("LLM_PROVIDER", "openai").lower()
        try:
            provider = ModelProvider(provider_str)
        except ValueError:
            provider = ModelProvider.OPENAI

        # Build model config
        model_config = ModelConfig(
            provider=provider,
            model_name=os.getenv("LLM_MODEL_NAME", "gpt-4o"),
            temperature=float(os.getenv("LLM_TEMPERATURE", "0.7")),
            max_tokens=int(os.getenv("LLM_MAX_TOKENS", "0")) or None,
            # API 配置
            api_key=os.getenv("OPENAI_API_KEY") or os.getenv("ANTHROPIC_API_KEY"),
            base_url=os.getenv("LLM_BASE_URL"),  # 自定义 API 地址
            api_version=os.getenv("LLM_API_VERSION"),  # API 版本
            timeout=int(os.getenv("LLM_TIMEOUT", "120")),
            max_retries=int(os.getenv("LLM_MAX_RETRIES", "3")),
        )

        # Check if LangSmith is properly configured
        langsmith_api_key = os.getenv("LANGCHAIN_API_KEY", "")
        langsmith_enabled = False
        if langsmith_api_key and langsmith_api_key != "ls__your_langsmith_api_key":
            langsmith_enabled = os.getenv("LANGCHAIN_TRACING_V2", "false").lower() == "true"

        return cls(
            model=model_config,
            langsmith_tracing=langsmith_enabled,
            langsmith_api_key=langsmith_api_key if langsmith_enabled else None,
            langsmith_project=os.getenv("LANGCHAIN_PROJECT", "scira-research-agent"),
            auto_approve=os.getenv("AUTO_APPROVE", "false").lower() == "true",
            max_literature_count=int(os.getenv("MAX_LITERATURE_COUNT", "20")),
        )


def get_llm_client(config: Optional[SciraConfig] = None) -> Any:
    """
    Get LLM client based on configuration.

    Returns a LangChain chat model instance.
    Supports OpenAI, Anthropic, and custom OpenAI-compatible APIs.
    """
    from langchain_openai import ChatOpenAI
    from langchain_anthropic import ChatAnthropic

    if config is None:
        config = SciraConfig.from_env()

    model_cfg = config.model

    # 获取 API key
    api_key = model_cfg.api_key
    if not api_key:
        if model_cfg.provider == ModelProvider.OPENAI or model_cfg.provider == ModelProvider.CUSTOM:
            api_key = os.getenv("OPENAI_API_KEY")
        elif model_cfg.provider == ModelProvider.ANTHROPIC:
            api_key = os.getenv("ANTHROPIC_API_KEY")

    if model_cfg.provider == ModelProvider.OPENAI:
        # 标准 OpenAI
        client_params = {
            "model": model_cfg.model_name,
            "temperature": model_cfg.temperature,
            "max_tokens": model_cfg.max_tokens,
            "api_key": api_key,
            "timeout": model_cfg.timeout,
            "max_retries": model_cfg.max_retries,
        }

        # 如果有自定义 base_url，使用它
        if model_cfg.base_url:
            client_params["base_url"] = model_cfg.base_url

        return ChatOpenAI(**client_params)

    elif model_cfg.provider == ModelProvider.ANTHROPIC:
        # Anthropic Claude
        return ChatAnthropic(
            model=model_cfg.model_name,
            temperature=model_cfg.temperature,
            max_tokens=model_cfg.max_tokens or 4096,
            api_key=api_key,
            timeout=model_cfg.timeout,
            max_retries=model_cfg.max_retries,
        )

    elif model_cfg.provider == ModelProvider.CUSTOM:
        # 自定义 OpenAI 兼容 API
        return ChatOpenAI(
            model=model_cfg.model_name,
            temperature=model_cfg.temperature,
            max_tokens=model_cfg.max_tokens,
            api_key=api_key,
            base_url=model_cfg.base_url,
            timeout=model_cfg.timeout,
            max_retries=model_cfg.max_retries,
        )

    else:
        raise ValueError(f"Unsupported provider: {model_cfg.provider}")


def get_model_provider() -> ModelProvider:
    """Get current model provider from environment."""
    provider_str = os.getenv("LLM_PROVIDER", "openai").lower()
    try:
        return ModelProvider(provider_str)
    except ValueError:
        return ModelProvider.OPENAI


def get_model_name() -> str:
    """Get current model name from environment."""
    return os.getenv("LLM_MODEL_NAME", "gpt-4o")


# Global config instance
_config: Optional[SciraConfig] = None


def get_config() -> SciraConfig:
    """Get global configuration singleton."""
    global _config
    if _config is None:
        _config = SciraConfig.from_env()
    return _config


def reset_config():
    """Reset global config (useful for testing)."""
    global _config
    _config = None
