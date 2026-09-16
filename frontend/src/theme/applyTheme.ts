import { ThemeTokens } from "./tokens";

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

/** Picks whichever of black/white gives better WCAG contrast against the given
 * #rrggbb background, so user-chosen button colors stay readable. */
function contrastTextColor(hex: string): "#000000" | "#ffffff" {
  const h = hex.replace("#", "");
  if (h.length !== 6) return "#ffffff";
  const toLinear = (c: number) => {
    const s = c / 255;
    return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
  };
  const r = toLinear(parseInt(h.slice(0, 2), 16));
  const g = toLinear(parseInt(h.slice(2, 4), 16));
  const b = toLinear(parseInt(h.slice(4, 6), 16));
  const luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b;
  // Contrast ratio against white (L=1) vs black (L=0); pick the higher one.
  const contrastWithWhite = 1.05 / (luminance + 0.05);
  const contrastWithBlack = (luminance + 0.05) / 0.05;
  return contrastWithWhite >= contrastWithBlack ? "#ffffff" : "#000000";
}

/**
 * Writes the tokens that need to be consumable from plain CSS/Tailwind
 * arbitrary-value classes (rather than via ThemeContext.resolve() + inline
 * `style`) as CSS custom properties on the document root: the primary button
 * color (plus a precomputed hover shade), the page background, and the
 * secondary/container background (Card/Navbar/Sidebar, via flowbiteTheme.ts,
 * plus a handful of manual card-tile surfaces). Every other token is read
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
  root.setProperty("--nc-bg2-light", theme.background2.light);
  root.setProperty("--nc-bg2-dark", theme.background2.dark);
}
