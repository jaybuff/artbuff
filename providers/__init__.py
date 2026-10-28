"""Art source registry.

To add a museum (Art Institute of Chicago, Rijksmuseum, ...):
  1. Create providers/<name>.py with a class implementing `Provider`
     (providers/base.py): `name`, `label`, `search()`, `get()`, `get_full_image()`.
  2. Import it here and add an instance to PROVIDERS.
That's it: routes, history and favorites key on (provider.name, art id).
"""
from .base import Artwork, Provider, SearchResult
from .met import MetProvider

PROVIDERS: dict[str, Provider] = {p.name: p for p in [MetProvider()]}
DEFAULT_PROVIDER = "met"


def get_provider(name: str) -> Provider:
    try:
        return PROVIDERS[name]
    except KeyError:
        raise KeyError(f"Unknown provider: {name}")


__all__ = ["Artwork", "Provider", "SearchResult", "PROVIDERS", "DEFAULT_PROVIDER", "get_provider"]
