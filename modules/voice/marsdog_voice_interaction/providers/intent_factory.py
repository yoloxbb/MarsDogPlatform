"""Explicit backend selection; optional CPU imports never load the RKLLM library."""
from .base import BaseProvider

def create_intent_provider(section: dict) -> BaseProvider | None:
    if not section.get("enabled", False) or section.get("type") == "mock":
        return None
    kind = section.get("type", "rkllm")
    if kind == "qwen_cpu":
        from .intent_qwen_cpu import IntentQwenCPUProvider
        return IntentQwenCPUProvider(section.get("config", {}))
    # Preserve the legacy RKLLM selection for existing enabled non-mock configurations.
    from .intent_rkllm import IntentRKLLMProvider
    return IntentRKLLMProvider(section.get("config", {}))
