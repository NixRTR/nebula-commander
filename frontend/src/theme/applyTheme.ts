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

/**
 * Writes the primary color (plus a precomputed hover shade) as CSS custom
 * properties on the document root. This is the only token that needs CSS
 * vars - it's consumed by the Flowbite Button "purple" override (see
 * flowbiteTheme.ts) via Tailwind arbitrary-value classes. Every other token
 * is read directly through ThemeContext.resolve() and applied via inline
 * `style`, which needs no CSS variable.
 */
export function applyPrimaryColor(theme: ThemeTokens): void {
  const root = document.documentElement.style;
  root.setProperty("--nc-primary-light", theme.primary.light);
  root.setProperty("--nc-primary-dark", theme.primary.dark);
  root.setProperty("--nc-primary-light-hover", darken(theme.primary.light, 0.15));
  root.setProperty("--nc-primary-dark-hover", darken(theme.primary.dark, 0.15));
}
