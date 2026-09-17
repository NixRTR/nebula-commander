import { ThemeTokens, contrastTextColor } from "./tokens";

/** Darkens a #rrggbb hex color by the given fraction (0-1), for a hover shade. */
function darken(hex: string, amount: number): string {
  const h = hex.replace("#", "");
  if (h.length !== 6) return hex;
  const clamp = (n: number) => Math.max(0, Math.min(255, Math.round(n)));
  const r = clamp(parseInt(h.slice(0, 2), 16) * (1 - amount));
  const g = clamp(parseInt(h.slice(2, 4), 16) * (1 - amount));
  const b = clamp(parseInt(h.slice(4, 6), 16) * (1 - amount));
  const toHex = (n: number) => n.toString(16).padStart(2, "0");
  return `#${toHex(r)}${toHex(g)}${toHex(b)}`;
}

/**
 * Writes the tokens that need to be consumable from plain CSS/Tailwind
 * arbitrary-value classes (rather than via ThemeContext.resolve() + inline
 * `style`) as CSS custom properties on the document root: the primary button
 * color (plus a precomputed hover shade), the page background, and the
 * secondary/container background (Card/Navbar/Sidebar/Modal/Toast, via
 * flowbiteTheme.ts, plus a handful of manual card-tile surfaces) - each paired
 * with a precomputed contrast text color (theme/tokens.ts's contrastTextColor)
 * so body copy and headings stay readable against whatever the user picks for
 * a background, the same way badges already do. Every other token is read
 * directly through ThemeContext.resolve() and applied via inline `style`.
 */
export function applyThemeCssVars(theme: ThemeTokens): void {
  const root = document.documentElement.style;
  root.setProperty("--nc-primary-light", theme.primary.light);
  root.setProperty("--nc-primary-dark", theme.primary.dark);
  root.setProperty("--nc-primary-light-hover", darken(theme.primary.light, 0.15));
  root.setProperty("--nc-primary-dark-hover", darken(theme.primary.dark, 0.15));
  root.setProperty("--nc-primary-light-contrast", contrastTextColor(theme.primary.light));
  root.setProperty("--nc-primary-dark-contrast", contrastTextColor(theme.primary.dark));
  root.setProperty("--nc-bg-light", theme.background.light);
  root.setProperty("--nc-bg-dark", theme.background.dark);
  root.setProperty("--nc-bg-light-contrast", contrastTextColor(theme.background.light));
  root.setProperty("--nc-bg-dark-contrast", contrastTextColor(theme.background.dark));
  root.setProperty("--nc-bg2-light", theme.background2.light);
  root.setProperty("--nc-bg2-dark", theme.background2.dark);
  root.setProperty("--nc-bg2-light-contrast", contrastTextColor(theme.background2.light));
  root.setProperty("--nc-bg2-dark-contrast", contrastTextColor(theme.background2.dark));
}
