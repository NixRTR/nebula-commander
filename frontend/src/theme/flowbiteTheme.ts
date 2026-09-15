import type { CustomFlowbiteTheme } from "flowbite-react";

/**
 * Remaps Flowbite's Button "purple" color slot to the user's configurable
 * primary color via CSS variables written by applyTheme.ts. Every existing
 * `color="purple"` call site across the app picks this up automatically -
 * no per-call-site changes needed. See ThemeContext / theme/tokens.ts.
 */
export const flowbiteTheme: CustomFlowbiteTheme = {
  button: {
    color: {
      purple:
        "border border-transparent bg-[var(--nc-primary-light)] text-white focus:ring-4 focus:ring-[var(--nc-primary-light)]/30 enabled:hover:bg-[var(--nc-primary-light-hover)] dark:bg-[var(--nc-primary-dark)] dark:focus:ring-[var(--nc-primary-dark)]/40 dark:enabled:hover:bg-[var(--nc-primary-dark-hover)]",
    },
  },
};
