# STUB — bodies owned by A5 (feat/m5-shell). Not frozen.
"""Inline SVG icons, transcribed from `design/nav-import-census/*.dc.html`.

All icons are a 24x24 viewBox, `fill:none; stroke:currentColor`, rendered at
the size the caller asks for. They are **inline** — no sprite sheet, no icon
font, nothing fetched (N1, §12.9).

Kept as strings rather than components so they can be dropped into any slot
with `ui.html(svg, tag="span")`.
"""

from typing import Final

__all__ = [
    "ALERT_TRIANGLE",
    "BAR_CHART",
    "CHECK",
    "CLIPBOARD",
    "DOWNLOAD",
    "INFO",
    "LIST",
    "NAV_ICONS",
    "PLAY_CIRCLE",
    "PLUS",
    "SLIDERS",
    "TABLE",
    "svg",
]


def svg(body: str, *, size: int, stroke: float = 1.8, join: bool = True) -> str:
    """Wrap icon path data in the design's standard `<svg>`."""
    linejoin = ' stroke-linejoin="round"' if join else ""
    return (
        f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" '
        f'stroke="currentColor" stroke-width="{stroke}" stroke-linecap="round"'
        f'{linejoin} aria-hidden="true" focusable="false">{body}</svg>'
    )


DOWNLOAD: Final = (
    '<path d="M12 3v11"></path><path d="m8 10 4 4 4-4"></path>'
    '<path d="M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2"></path>'
)
BAR_CHART: Final = (
    '<path d="M4 20V10"></path><path d="M10 20V4"></path>'
    '<path d="M16 20v-7"></path><path d="M22 20H2"></path>'
)
LIST: Final = (
    '<path d="M8 6h13"></path><path d="M8 12h13"></path><path d="M8 18h13"></path>'
    '<path d="M3 6h.01"></path><path d="M3 12h.01"></path><path d="M3 18h.01"></path>'
)
SLIDERS: Final = (
    '<path d="M4 6h10"></path><path d="M18 6h2"></path><path d="M4 12h4"></path>'
    '<path d="M12 12h8"></path><path d="M4 18h12"></path>'
    '<circle cx="16" cy="6" r="2"></circle><circle cx="10" cy="12" r="2"></circle>'
    '<circle cx="18" cy="18" r="2"></circle>'
)
PLAY_CIRCLE: Final = '<circle cx="12" cy="12" r="9"></circle><path d="m10 8 6 4-6 4z"></path>'
TABLE: Final = (
    '<rect x="3" y="4" width="18" height="16" rx="1.5"></rect>'
    '<path d="M3 10h18"></path><path d="M9 10v10"></path>'
)
ALERT_TRIANGLE: Final = (
    '<path d="M10.3 4.3 2.5 18a1.7 1.7 0 0 0 1.5 2.5h16a1.7 1.7 0 0 0 1.5-2.5'
    'L13.7 4.3a1.7 1.7 0 0 0-3 0Z"></path>'
    '<path d="M12 9v4"></path><path d="M12 17h.01"></path>'
)
CHECK: Final = '<path d="m5 13 4 4 10-10"></path>'
PLUS: Final = '<path d="M12 5v14"></path><path d="M5 12h14"></path>'
CLIPBOARD: Final = (
    '<path d="M8 3H6a1.6 1.6 0 0 0-1.6 1.6v14.8A1.6 1.6 0 0 0 6 21h12a1.6 1.6 0 0 0 '
    '1.6-1.6V4.6A1.6 1.6 0 0 0 18 3h-2"></path>'
    '<rect x="8" y="2" width="8" height="3.4" rx="1"></rect>'
    '<path d="M8.5 11h7"></path><path d="M8.5 15h4.5"></path>'
)
INFO: Final = (
    '<circle cx="12" cy="12" r="9"></circle><path d="M12 11v5"></path><path d="M12 8h.01"></path>'
)

#: Nav key -> icon body. The mapping the design README's nav table specifies.
NAV_ICONS: Final[dict[str, str]] = {
    "import": DOWNLOAD,
    "census": BAR_CHART,
    "codelists": LIST,
    "features": SLIDERS,
    "evaluation": PLAY_CIRCLE,
    "results": TABLE,
    "mismatches": ALERT_TRIANGLE,
}
