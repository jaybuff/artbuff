from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class Artwork:
    id: str
    title: str
    artist: str
    thumbnail_url: str
    source: str
    # Detail-view extras; empty in search results.
    date: str = ""
    medium: str = ""
    page_url: str = ""
    preview_url: str = ""
    extra: dict = field(default_factory=dict)


@dataclass
class SearchResult:
    items: list[Artwork]
    total: int


class Provider(Protocol):
    """Interface every art source implements. See providers/__init__.py.

    Optional lazy-loading hooks (so a grid only looks up the items actually on screen):
      search_ids(query, page, per_page, filters) -> (ids, total)   # one cheap call, no per-item lookups
      peek(art_id) -> Artwork | None    # local cache only; None = unknown, KeyError = known unusable

    Optional discovery hooks (the UI shows the matching controls only if a provider has them):
      discovery() -> {"presets": [{"label", "params"}], "departments": [{"id", "name"}],
                      "eras": [{"label", "from", "to"}]}
      related(art) -> [{"label", "params"}]   # "more like this" links; params are URL query params
    """

    name: str  # short id used in URLs and the DB, e.g. "met"
    label: str  # human-readable, e.g. "The Met"

    def search(
        self, query: str, page: int = 1, per_page: int = 24, filters: dict[str, str] | None = None
    ) -> SearchResult:
        """`filters` holds provider-specific URL params (see `discovery`); ignore ones you don't know."""
        ...

    def get(self, art_id: str) -> Artwork: ...

    def get_thumbnail(self, art_id: str) -> bytes:
        """Small preview image bytes (cached locally)."""
        ...

    def get_full_image(self, art_id: str) -> tuple[bytes, str]:
        """Return (image bytes, content type)."""
        ...
