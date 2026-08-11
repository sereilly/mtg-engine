"""Guard: every first-party asset `index.html` loads is served no-store.

The middleware used to match a hand-written set of paths, and it had fallen
behind the page: `/sfx.js`, `/music.js` and `/legality.js` were loaded by
`index.html` and absent from the set, so those three alone were browser-cacheable
while their siblings were not. Nothing noticed because the `?v=` query strings
the page carries are the real cache-bust today — and the middleware matches on
`path`, so it never sees them. A stale-script bug would therefore have appeared
only for whoever edited one of those three without bumping its `?v=`.

Adding the three names would have restored the same gap at the next script. So
the set is derived from the directory, and this test derives its expectation
from `index.html` — the two are computed from different places on purpose, and
the test is only worth something while that stays true.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from web.app import _NO_CACHE_PATHS, _VENDORED_ASSETS
from web.runtime import STATIC_DIR

_ASSET_REF = re.compile(r'(?:src|href)="(/[^"]+)"')
_SHELL_SUFFIXES = (".js", ".css", ".html")


def _assets_index_html_loads() -> set[str]:
    """First-party shell assets referenced by the page, `?v=` stripped.

    Absolute URLs (the Google Fonts links) do not match, since the pattern
    requires a leading slash — they are another origin's problem.
    """
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    paths = {ref.split("?")[0] for ref in _ASSET_REF.findall(html)}
    return {path for path in paths if path.endswith(_SHELL_SUFFIXES)}


def test_index_html_loads_something():
    """The other tests are vacuous if the page stops referencing assets."""
    assets = _assets_index_html_loads()
    assert len(assets) >= 8, f"suspiciously few assets parsed from index.html: {assets}"


@pytest.mark.parametrize("asset", sorted(_assets_index_html_loads()))
def test_first_party_shell_assets_are_no_store(asset):
    if Path(asset).name in _VENDORED_ASSETS:
        pytest.skip(f"{asset} is vendored and version-pinned — cacheable on purpose")
    assert asset in _NO_CACHE_PATHS, (
        f"{asset} is loaded by index.html but is not in the no-store set, so a "
        "browser may serve a stale copy of it while its siblings refresh"
    )


def test_vendored_assets_stay_cacheable():
    """The exemption is deliberate, not an oversight — pin it so it reads that way.

    `anime.min.js` is third-party and pinned by version; no-storing it would
    re-download it on every page load for no benefit. If a vendored file ever
    needs to be no-store, that is a decision to make here rather than a drift.
    """
    for name in _VENDORED_ASSETS:
        assert f"/{name}" not in _NO_CACHE_PATHS, name
        assert (STATIC_DIR / name).exists(), (
            f"{name} is exempted from no-store but is not in web/static/ — a "
            "stale exemption silently widens to nothing, or to a future file "
            "that reuses the name"
        )


def test_media_directories_are_not_no_store():
    """Only the shell. `images/`, `music/`, `sfx/` and `symbols/` are megabytes
    of content that never change under an unchanged name, and no-storing them
    would re-download them on every poll."""
    for path in _NO_CACHE_PATHS:
        assert path == "/" or path.count("/") == 1, (
            f"{path} is below the top level of web/static/ — the no-store set "
            "is the app shell, not the media"
        )


def test_the_no_cache_set_covers_the_api():
    """Not derived from the directory, so it needs saying out loud."""
    from web.app import _no_cache_assets  # noqa: F401  (import proves it exists)

    # The middleware special-cases the /api/ prefix rather than listing routes;
    # this asserts the *directory* half never accidentally starts claiming it.
    assert not any(path.startswith("/api") for path in _NO_CACHE_PATHS)
