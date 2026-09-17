import type { CustomFlowbiteTheme } from "flowbite-react";

/**
 * Remaps Flowbite's Button "purple" color slot to the user's configurable
 * primary color, and the Card/Navbar/Sidebar/Modal/Toast container
 * backgrounds to the "background2" token, via CSS variables written by
 * theme/applyTheme.ts. Text color on each (including individual Sidebar
 * items, whose label/hover/active states are otherwise hardcoded by
 * Flowbite) is computed per-theme (theme/tokens.ts's contrastTextColor) as
 * whichever of near-black/near-white contrasts better against that surface's
 * actual color, so a light/bright user-chosen color never washes out to
 * unreadable same-on-same text. Every existing `color="purple"` Button and
 * every Card/Navbar/Sidebar/Modal/Toast usage across the app picks this up
 * automatically - no per-call-site changes needed. See ThemeContext /
 * theme/tokens.ts.
 *
 * The base strings below are copied byte-for-byte from the installed
 * flowbite-react version's defaults (node_modules/flowbite-react/lib/esm/
 * components/{Card,Navbar,Sidebar,Modal,Toast}/theme.js), with only the
 * background/text utility classes swapped for CSS vars - every other class
 * must stay identical, or that component silently loses styling. Re-diff
 * against the installed theme.js files on any flowbite-react version bump.
 */
export const flowbiteTheme: CustomFlowbiteTheme = {
  button: {
    color: {
      purple:
        "border border-transparent bg-[var(--nc-primary-light)] text-[var(--nc-primary-light-contrast)] focus:ring-4 focus:ring-[var(--nc-primary-light)]/30 enabled:hover:bg-[var(--nc-primary-light-hover)] dark:bg-[var(--nc-primary-dark)] dark:text-[var(--nc-primary-dark-contrast)] dark:focus:ring-[var(--nc-primary-dark)]/40 dark:enabled:hover:bg-[var(--nc-primary-dark-hover)]",
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
    item: {
      // Hover/active use a translucent tint of the item's own (already
      // contrast-correct) text color via color-mix(), rather than a fixed
      // gray, so the highlight stays visible against any background2 color.
      base: "flex items-center justify-center rounded-lg p-2 text-base font-normal text-[var(--nc-bg2-light-contrast)] hover:bg-[color-mix(in_srgb,currentColor_10%,transparent)] dark:text-[var(--nc-bg2-dark-contrast)] dark:hover:bg-[color-mix(in_srgb,currentColor_10%,transparent)]",
      active: "bg-[color-mix(in_srgb,currentColor_15%,transparent)] dark:bg-[color-mix(in_srgb,currentColor_15%,transparent)]",
    },
  },
  modal: {
    content: {
      inner:
        "relative flex max-h-[90dvh] flex-col rounded-lg bg-[var(--nc-bg2-light)] shadow dark:bg-[var(--nc-bg2-dark)]",
    },
    header: {
      title: "text-xl font-medium text-[var(--nc-bg2-light-contrast)] dark:text-[var(--nc-bg2-dark-contrast)]",
    },
  },
  toast: {
    root: {
      base: "flex w-full max-w-xs items-center rounded-lg bg-[var(--nc-bg2-light)] p-4 text-[var(--nc-bg2-light-contrast)] shadow dark:bg-[var(--nc-bg2-dark)] dark:text-[var(--nc-bg2-dark-contrast)]",
    },
  },
};
