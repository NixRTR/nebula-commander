import type { CustomFlowbiteTheme } from "flowbite-react";

/**
 * Remaps Flowbite's Button "purple" color slot to the user's configurable
 * primary color, and the Card/Navbar/Sidebar container backgrounds to the
 * "background2" token, via CSS variables written by theme/applyTheme.ts.
 * Every existing `color="purple"` Button and every Card/Navbar/Sidebar usage
 * across the app picks this up automatically - no per-call-site changes
 * needed. See ThemeContext / theme/tokens.ts.
 *
 * The base strings below are copied byte-for-byte from the installed
 * flowbite-react version's defaults (node_modules/flowbite-react/lib/esm/
 * components/{Card,Navbar,Sidebar}/theme.js), with only the background
 * utility classes swapped for CSS vars - every other class must stay
 * identical, or that component silently loses styling. Re-diff against the
 * installed theme.js files on any flowbite-react version bump.
 */
export const flowbiteTheme: CustomFlowbiteTheme = {
  button: {
    color: {
      purple:
        "border border-transparent bg-[var(--nc-primary-light)] text-white focus:ring-4 focus:ring-[var(--nc-primary-light)]/30 enabled:hover:bg-[var(--nc-primary-light-hover)] dark:bg-[var(--nc-primary-dark)] dark:focus:ring-[var(--nc-primary-dark)]/40 dark:enabled:hover:bg-[var(--nc-primary-dark-hover)]",
    },
  },
  card: {
    root: {
      base: "flex rounded-lg border border-gray-200 bg-[var(--nc-bg2-light)] shadow-md dark:border-gray-700 dark:bg-[var(--nc-bg2-dark)]",
    },
  },
  navbar: {
    root: {
      base: "bg-[var(--nc-bg2-light)] px-2 py-2.5 dark:border-gray-700 dark:bg-[var(--nc-bg2-dark)] sm:px-4",
    },
  },
  sidebar: {
    root: {
      inner:
        "h-full overflow-y-auto overflow-x-hidden rounded bg-[var(--nc-bg2-light)] px-3 py-4 dark:bg-[var(--nc-bg2-dark)]",
    },
  },
};
