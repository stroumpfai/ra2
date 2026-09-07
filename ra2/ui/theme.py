# STUB — bodies owned by A5 (feat/m5-shell). Not frozen.
"""Design tokens -> CSS custom properties, in **one** injection (§8.2).

Two things here are non-negotiable and have tests behind them:

- **Fonts are vendored.** IBM Plex Sans and Mono (400/500/600) ship in
  `ui/static/fonts/` and are served by the app with local `@font-face`. The
  design README says "loaded from Google Fonts"; **N1 forbids any CDN fetch**
  and N1 wins (SD3). J6 fails the build on any request to another host.
- Colour carries **only** state and severity. No decorative hue.
"""

from pathlib import Path
from typing import Final

__all__ = ["FONTS_DIR", "FONTS_URL_PATH", "inject"]

#: Served by the app itself. Nothing is fetched over the network (N1, §12.9).
FONTS_DIR: Final = Path(__file__).parent / "static" / "fonts"
FONTS_URL_PATH: Final = "/static/fonts"


def inject() -> None:
    """Inject the token stylesheet and the utility classes, once per page.

    A5 adds the oklch tokens from `design/nav-import-census/README.md` and
    `.card .th .td .navitem .lbl .chip .btn .bar .tick .sorth`, plus a visible
    focus ring from one token (the mock leaves focus undesigned).
    """
    raise NotImplementedError
