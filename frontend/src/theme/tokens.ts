/**
 * Default per-user color theme tokens - mirrors backend/theme_defaults.py exactly.
 * Update both files together; there's no cross-language codegen here.
 *
 * Every value is a plain 6-digit hex string (no alpha), so every token can be edited
 * with a plain <input type="color">. Dark-mode status colors used to be a Tailwind
 * opacity suffix (e.g. `dark:bg-green-900/40`) - each dark default below is the
 * flattened solid equivalent of that blend against Flowbite's Card dark background
 * (`dark:bg-gray-800`, #1f2937), so the default look is pixel-identical to before.
 */

export interface ThemeTokenValue {
  light: string;
  dark: string;
}

export type ThemeTokenKey =
  | "primary"
  | "status.neverActive"
  | "status.active"
  | "status.inactive"
  | "badge.lighthouse"
  | "badge.relay"
  | "badge.ios"
  | "badge.android"
  | "badge.windows"
  | "badge.linux"
  | "badge.macos"
  | "badge.node"
  | "group.restricted"
  | "group.open"
  | "diagram.edge";

export type ThemeTokens = Record<ThemeTokenKey, ThemeTokenValue>;

export const DEFAULT_THEME: ThemeTokens = {
  // Primary action color (Flowbite Button "purple" today: bg-purple-700 light, dark:bg-purple-600).
  primary: { light: "#7e22ce", dark: "#9333ea" },
  // Nodes page status card backgrounds.
  "status.neverActive": { light: "#f3f4f6", dark: "#1f2937" }, // gray-100 / gray-800
  "status.active": { light: "#dcfce7", dark: "#1b3a33" }, // green-100 / green-900@40% over gray-800
  "status.inactive": { light: "#fee2e2", dark: "#3c252f" }, // red-100 / red-900@30% over gray-800
  // Nodes page type/OS badge backgrounds (foreground text is computed from contrast at render time).
  "badge.lighthouse": { light: "#f3e8ff", dark: "#e9d5ff" }, // purple-100 / purple-200
  "badge.relay": { light: "#e0e7ff", dark: "#c7d2fe" }, // indigo-100 / indigo-200
  "badge.ios": { light: "#cffafe", dark: "#a5f3fc" }, // cyan-100 / cyan-200
  "badge.android": { light: "#ecfccb", dark: "#d9f99d" }, // lime-100 / lime-200
  "badge.windows": { light: "#dbeafe", dark: "#bfdbfe" }, // blue-100 / blue-200
  "badge.linux": { light: "#fef9c3", dark: "#fef08a" }, // yellow-100 / yellow-200
  "badge.macos": { light: "#4b5563", dark: "#111827" }, // gray-600 / gray-900 (Flowbite "dark" variant)
  "badge.node": { light: "#f3f4f6", dark: "#374151" }, // gray-100 / gray-700
  // Groups page dot + GroupAccessDiagram fill/stroke (mode-invariant today).
  "group.restricted": { light: "#a855f7", dark: "#a855f7" }, // purple-500
  "group.open": { light: "#9ca3af", dark: "#9ca3af" }, // gray-400
  // GroupAccessDiagram edge/arrow stroke.
  "diagram.edge": { light: "#9ca3af", dark: "#6b7280" }, // gray-400 / gray-500
};

/** Simple relative-luminance check so badge/status text stays legible against any
 * user-chosen background, without storing a separate foreground color per token. */
export function contrastTextColor(bgHex: string): string {
  const hex = bgHex.replace("#", "");
  if (hex.length !== 6) return "#111827";
  const r = parseInt(hex.slice(0, 2), 16) / 255;
  const g = parseInt(hex.slice(2, 4), 16) / 255;
  const b = parseInt(hex.slice(4, 6), 16) / 255;
  const linear = (c: number) => (c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4));
  const luminance = 0.2126 * linear(r) + 0.7152 * linear(g) + 0.0722 * linear(b);
  return luminance > 0.5 ? "#111827" : "#f9fafb";
}
