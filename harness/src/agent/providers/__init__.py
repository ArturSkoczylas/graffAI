from .anthropic_provider import AnthropicProvider

_IMPLEMENTED = {
    "claude": AnthropicProvider,
    "anthropic": AnthropicProvider,
}
_KNOWN_NOT_IMPLEMENTED = {"openai", "gpt", "chatgpt"}


def get_provider(name: str, *, model: str, api_key: str, **options):
    key = (name or "").strip().lower()
    if key in _IMPLEMENTED:
        return _IMPLEMENTED[key](model=model, api_key=api_key, **options)
    if key in _KNOWN_NOT_IMPLEMENTED:
        raise NotImplementedError(
            f"Provider {name!r} is planned but not yet implemented."
        )
    raise ValueError(f"Unknown AI provider: {name!r}. Available: {sorted(_IMPLEMENTED)}")


__all__ = [
    "AnthropicProvider",
    "get_provider",
]
