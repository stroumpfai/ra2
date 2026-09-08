# STUB — bodies owned by A5 (feat/m5-shell). Not frozen.
"""Design tokens -> CSS custom properties, in **one** injection (§8.2).

Two things here are non-negotiable and have tests behind them:

- **Fonts are vendored.** IBM Plex Sans and Mono (400/500/600) ship in
  `ui/static/fonts/` and are served by the app with local `@font-face`. The
  design README says "loaded from Google Fonts"; **N1 forbids any CDN fetch**
  and N1 wins (SD3). J6 fails the build on any request to another host.
- Colour carries **only** state and severity. No decorative hue.

Every value below is `design/nav-import-census/README.md` §"Design Tokens" and
§"Fixed sizes worth keeping", transcribed. Nothing here is invented; where the
README and the `.dc.html` prototypes disagree (the prototype's `--accent` is a
blue left over from an earlier pass), **the README wins** — it is the handoff.
"""

from pathlib import Path
from typing import Final

from nicegui import ui

__all__ = [
    "BAR_HEIGHT_PX",
    "BAR_WIDTH_PX",
    "CARD_HEADER_HEIGHT_PX",
    "DIST_BAR_HEIGHT_PX",
    "DIST_BAR_MAX_WIDTH_PX",
    "FONTS_DIR",
    "FONTS_URL_PATH",
    "IMPORT_WELL_HEIGHT_PX",
    "STYLESHEET",
    "inject",
]

#: Served by the app itself. Nothing is fetched over the network (N1, §12.9).
FONTS_DIR: Final = Path(__file__).parent / "static" / "fonts"
FONTS_URL_PATH: Final = "/static/fonts"

# --- Fixed sizes the design calls load-bearing; asserted in E2E (§8.2) -------

#: Nav column and the brand cell above it — one continuous vertical rule.
CARD_HEADER_HEIGHT_PX: Final = 46
#: 10 rows + the header row, so the two Import cards match height exactly.
IMPORT_WELL_HEIGHT_PX: Final = 404
BAR_WIDTH_PX: Final = 78
BAR_HEIGHT_PX: Final = 6
DIST_BAR_HEIGHT_PX: Final = 8
DIST_BAR_MAX_WIDTH_PX: Final = 230

#: Stacked-bar segment shades, in rank order (README "distribution shades").
DIST_SHADES: Final[tuple[str, ...]] = (
    "var(--ink2)",
    "oklch(0.70 0.008 260)",
    "oklch(0.80 0.006 260)",
    "oklch(0.88 0.005 260)",
)

_FONT_FACES: Final[tuple[tuple[str, str, int], ...]] = (
    ("IBM Plex Sans", "IBMPlexSans-Regular.woff2", 400),
    ("IBM Plex Sans", "IBMPlexSans-Medium.woff2", 500),
    ("IBM Plex Sans", "IBMPlexSans-SemiBold.woff2", 600),
    ("IBM Plex Mono", "IBMPlexMono-Regular.woff2", 400),
    ("IBM Plex Mono", "IBMPlexMono-Medium.woff2", 500),
    ("IBM Plex Mono", "IBMPlexMono-SemiBold.woff2", 600),
)


def _font_face(family: str, filename: str, weight: int) -> str:
    """One local `@font-face`. The URL is app-relative — never a CDN (N1)."""
    return (
        "@font-face{"
        f"font-family:'{family}';font-style:normal;font-weight:{weight};"
        f"font-display:block;src:url('{FONTS_URL_PATH}/{filename}') format('woff2');"
        "}"
    )


_FONTS: Final = "".join(_font_face(*face) for face in _FONT_FACES)

_TOKENS: Final = """
:root{
  --ink:oklch(0.22 0.012 260);
  --ink2:oklch(0.47 0.010 260);
  --ink3:oklch(0.63 0.008 260);
  --rule:oklch(0.895 0.006 260);
  --rule2:oklch(0.945 0.004 260);
  --bg:oklch(0.976 0.004 95);
  --surface:oklch(1 0 0);
  --accent:oklch(0.50 0.008 260);
  --accent-soft:oklch(0.935 0.004 260);
  --ok:oklch(0.50 0.11 152);
  --warn:oklch(0.56 0.13 72);
  --warn-soft:oklch(0.965 0.035 80);
  --danger:oklch(0.53 0.15 27);
  --danger-soft:oklch(0.962 0.030 27);
  --note-ink:oklch(0.38 0.10 255);
  --muted-arrow:oklch(0.80 0.006 260);
  --dist-1:oklch(0.47 0.010 260);
  --dist-2:oklch(0.70 0.008 260);
  --dist-3:oklch(0.80 0.006 260);
  --dist-4:oklch(0.88 0.005 260);
  --focus:oklch(0.52 0.13 255);
  --sans:'IBM Plex Sans',ui-sans-serif,system-ui,sans-serif;
  --mono:'IBM Plex Mono',ui-monospace,SFMono-Regular,Menlo,monospace;
  --nav-w:196px;
  --card-header-h:46px;
  --import-well-h:404px;
  --bar-w:78px;
  --bar-h:6px;
  --dist-bar-h:8px;
  --dist-bar-max-w:230px;
}
"""

# Quasar/Tailwind reset. NiceGUI ships both; the design is an instrument panel
# with 1px rules and no shadows, so their body font, page padding and card
# elevation are turned off here rather than fought per component (§8.2).
_RESET: Final = """
*{box-sizing:border-box;}
html,body{margin:0;padding:0;height:100%;}
body,.q-layout,.nicegui-content{
  font-family:var(--sans);
  font-size:13px;
  line-height:1.45;
  color:var(--ink);
  background:var(--bg);
  -webkit-font-smoothing:antialiased;
}
.nicegui-content{padding:0;gap:0;}
.q-page,.q-page-container{padding:0!important;min-height:0;}
.ra2-root{display:flex;flex-direction:column;height:100vh;background:var(--bg);}
/* Quasar sizes `h1` at 6rem/6rem weight 300. Every heading in this design is
   set by its own rule, so the base is neutralised here rather than overridden
   six times. Without this the header block is 145px instead of ~60px. */
h1,h2,h3,h4,h5,h6{
  margin:0;font-size:inherit;font-weight:600;line-height:1.25;letter-spacing:normal;
}
table{border-collapse:collapse;width:100%;}
.mono{font-family:var(--mono);}
.nowrap{white-space:nowrap;}
"""

_UTILITIES: Final = """
.lbl{
  white-space:nowrap;font-family:var(--mono);font-size:10px;letter-spacing:.09em;
  text-transform:uppercase;color:var(--ink3);font-weight:500;
}
.card{
  background:var(--surface);border:1px solid var(--rule);border-radius:3px;
}
.card-header{
  display:flex;align-items:center;justify-content:space-between;gap:10px;
  flex-wrap:nowrap;padding:0 14px;height:var(--card-header-h);flex:none;
  overflow:hidden;border-bottom:1px solid var(--rule);
}
.th{
  font-family:var(--mono);font-size:10px;letter-spacing:.07em;text-transform:uppercase;
  color:var(--ink3);font-weight:500;white-space:nowrap;padding:0 9px 7px;padding-top:10px;
  border-bottom:1px solid var(--rule);text-align:left;background:var(--surface);
}
.td{
  padding:8px 9px;white-space:nowrap;border-bottom:1px solid var(--rule2);
  font-size:12.5px;vertical-align:middle;
}
.wide .th{padding:10px 12px 7px;}
.wide .td{padding:8px 12px;}
.navitem{
  display:flex;align-items:center;gap:9px;padding:6px 14px;color:var(--ink2);
  font-size:12.5px;border-left:2px solid transparent;text-decoration:none;
  transition:background-color 120ms ease,color 120ms ease;
}
.navitem:hover{color:var(--ink);background:var(--rule2);text-decoration:none;}
.navitem.on{
  color:var(--ink);background:var(--accent-soft);border-left-color:var(--accent);
  font-weight:500;
}
.chip{
  display:inline-flex;align-items:center;gap:8px;border:1px solid var(--rule);
  border-radius:3px;padding:4px 9px;background:var(--surface);
  font-family:var(--mono);font-size:11px;color:var(--ink);white-space:nowrap;
}
.chip .caret{color:var(--ink3);font-size:9px;}
.btn{
  display:inline-flex;align-items:center;gap:7px;border-radius:3px;padding:8px 16px;
  font-size:12.5px;font-weight:500;border:1px solid transparent;cursor:pointer;
  font-family:var(--sans);
}
.btn.primary{background:var(--accent);color:#fff;}
.btn.secondary{
  background:var(--surface);color:var(--ink);border-color:var(--rule);padding:7px 14px;
}
.iconbtn{
  display:inline-flex;align-items:center;justify-content:center;
  border:1px solid var(--rule);border-radius:3px;background:var(--surface);
  color:var(--ink2);cursor:pointer;padding:0;
}
/* Named `iconbtn-sm` / `iconbtn-md`, never `sm` / `md`: those are Quasar's
   breakpoint visibility helpers and they carry `display:none!important`, which
   makes every icon button vanish on most screens. */
.iconbtn-sm{width:22px;height:22px;color:var(--ink3);}
.iconbtn-md{width:24px;height:24px;}
.iconbtn[disabled]{color:var(--muted-arrow);cursor:default;}
.tick{
  display:inline-flex;align-items:center;justify-content:center;width:14px;height:14px;
  border:1px solid var(--ink3);border-radius:2px;color:transparent;
  background:var(--surface);vertical-align:middle;cursor:pointer;flex:none;
}
.tick.on{background:var(--accent);border-color:var(--accent);color:#fff;}
.tick.mixed{background:var(--accent);border-color:var(--accent);color:#fff;}
.sorth{display:inline-flex;align-items:center;gap:5px;cursor:pointer;}
.sarr{font-size:9px;line-height:1;color:var(--muted-arrow);letter-spacing:-1px;}
.sarr.on{color:var(--ink);}
.bar{
  height:var(--bar-h);width:var(--bar-w);background:var(--rule2);border-radius:1px;
  overflow:hidden;flex:none;
}
.bar>i{display:block;height:100%;background:var(--ink3);}
.distbar{max-width:var(--dist-bar-max-w);}
.distbar>.track{
  display:flex;height:var(--dist-bar-h);border-radius:1px;overflow:hidden;
  background:var(--rule2);
}
.distbar>.track>i{display:block;height:100%;}
.distbar>.legend{
  font-family:var(--mono);font-size:10px;color:var(--ink3);margin-top:4px;
  letter-spacing:.01em;
}
.pagerow{
  flex:none;display:flex;align-items:center;justify-content:space-between;gap:12px;
  padding:9px 14px;border-top:1px solid var(--rule);
}
.pill{
  background:var(--accent-soft);color:var(--accent);padding:2px 7px;border-radius:3px;
  font-family:var(--mono);font-size:10.5px;font-weight:500;white-space:nowrap;
}
.ok{color:var(--ok);}
.warn{color:var(--warn);}
.danger{color:var(--danger);}
"""

# Focus is undesigned in the mock (README §"`.navitem` states"). One token,
# one rule, visible on every interactive element — keyboard nav is obvious.
_FOCUS: Final = """
:focus{outline:none;}
:focus-visible{
  outline:2px solid var(--focus);
  outline-offset:1px;
  border-radius:3px;
}
"""

#: The single stylesheet. One injection, not scattered across components (§8.2).
STYLESHEET: Final = _FONTS + _TOKENS + _RESET + _UTILITIES + _FOCUS


def inject() -> None:
    """Inject the token stylesheet and the utility classes, once per page.

    `shared=True` puts it in the head of every page NiceGUI serves, so it is
    written once per process rather than once per render.
    """
    ui.add_css(STYLESHEET, shared=True)
