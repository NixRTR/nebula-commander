"""
Default per-user color theme tokens.

Single source of truth for the theme token set and defaults - mirrored in
frontend/src/theme/tokens.ts (kept in sync by hand; there's no cross-language
codegen here, so update both files together).

Every value is a plain 6-digit hex string (no alpha) - see docs/plan notes on why
alpha was dropped: dark-mode status colors historically used Tailwind opacity
suffixes (e.g. `dark:bg-green-900/40`), which a plain `<input type="color">` can't
edit. Each dark default below is the flattened solid equivalent of that blend
instead, computed once against the Card component's actual dark background
(Flowbite's `dark:bg-gray-800`, #1f2937) so the default look is pixel-identical to
today's.
"""
from typing import TypedDict


class ThemeTokenValue(TypedDict):
    light: str
    dark: str


DEFAULT_THEME: dict[str, ThemeTokenValue] = {
    # Page background (App.tsx <main>, index.css body) and secondary/container
    # background (Card/Navbar/Sidebar and manual card-tile surfaces).
    "background": {"light": "#f9fafb", "dark": "#111827"},  # gray-50 / gray-900
    "background2": {"light": "#ffffff", "dark": "#1f2937"},  # white / gray-800
    # Primary action color (Flowbite Button "purple" today: bg-purple-700 light,
    # dark:bg-purple-600).
    "primary": {"light": "#7e22ce", "dark": "#9333ea"},
    # Nodes page status card backgrounds.
    "status.neverActive": {"light": "#f3f4f6", "dark": "#1f2937"},  # gray-100 / gray-800
    "status.active": {"light": "#dcfce7", "dark": "#1b3a33"},  # green-100 / green-900@40% over gray-800
    "status.inactive": {"light": "#fee2e2", "dark": "#3c252f"},  # red-100 / red-900@30% over gray-800
    # Nodes page type/OS badge backgrounds (foreground text is computed from
    # contrast at render time, not stored - see frontend theme docs).
    "badge.lighthouse": {"light": "#f3e8ff", "dark": "#e9d5ff"},  # purple-100 / purple-200
    "badge.relay": {"light": "#e0e7ff", "dark": "#c7d2fe"},  # indigo-100 / indigo-200
    "badge.ios": {"light": "#cffafe", "dark": "#a5f3fc"},  # cyan-100 / cyan-200
    "badge.android": {"light": "#ecfccb", "dark": "#d9f99d"},  # lime-100 / lime-200
    "badge.windows": {"light": "#dbeafe", "dark": "#bfdbfe"},  # blue-100 / blue-200
    "badge.linux": {"light": "#fef9c3", "dark": "#fef08a"},  # yellow-100 / yellow-200
    "badge.macos": {"light": "#4b5563", "dark": "#111827"},  # gray-600 / gray-900 (Flowbite "dark" variant)
    "badge.node": {"light": "#f3f4f6", "dark": "#374151"},  # gray-100 / gray-700
    # Groups page dot + GroupAccessDiagram fill/stroke (mode-invariant today).
    "group.restricted": {"light": "#a855f7", "dark": "#a855f7"},  # purple-500
    "group.open": {"light": "#9ca3af", "dark": "#9ca3af"},  # gray-400
    # GroupAccessDiagram edge/arrow stroke.
    "diagram.edge": {"light": "#9ca3af", "dark": "#6b7280"},  # gray-400 / gray-500
}

ALLOWED_TOKEN_KEYS = set(DEFAULT_THEME)
