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
            f"Dostawca {name!r} jest zaplanowany, ale jeszcze nie zaimplementowany."
        )
    raise ValueError(f"Nieznany dostawca AI: {name!r}. Dostępni: {sorted(_IMPLEMENTED)}")


__all__ = [
    "AnthropicProvider",
    "get_provider",
]
