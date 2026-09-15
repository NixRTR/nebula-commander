import React from "react";
import ReactDOM from "react-dom/client";
import { Flowbite } from "flowbite-react";
import App from "./App";
import { ThemeProvider } from "./contexts/ThemeContext";
import { flowbiteTheme } from "./theme/flowbiteTheme";
import { applyPrimaryColor } from "./theme/applyTheme";
import { DEFAULT_THEME } from "./theme/tokens";
import "./index.css";

// Seed the primary-color CSS vars with the defaults before mount, so the
// Flowbite Button "purple" override (which reads them via `var(...)`) always
// has a valid value on first paint. ThemeContext overwrites these with the
// user's saved theme shortly after mount once GET /me/theme resolves.
applyPrimaryColor(DEFAULT_THEME);

// Initialize dark/light mode from localStorage or system preference, before
// React mounts, so there's no flash of the wrong mode. ThemeContext reads
// this class back on mount rather than re-deciding, so the two can't disagree.
const theme = localStorage.getItem('theme');
const initialIsDark = theme === 'dark' || (!theme && window.matchMedia('(prefers-color-scheme: dark)').matches);
if (initialIsDark) {
  document.documentElement.classList.add('dark');
} else {
  document.documentElement.classList.remove('dark');
}

// Flowbite's own <Flowbite> wrapper independently manages the `dark` class
// via its own `flowbite-theme-mode` localStorage key (unrelated to ours) as
// soon as it mounts, defaulting to "light" if that key was never set - which
// would silently undo the class set above. Passing `mode` explicitly here
// seeds Flowbite's internal state to match, so it never fights our own
// dark/light toggle (owned by ThemeContext).
ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <Flowbite theme={{ mode: initialIsDark ? 'dark' : 'light', theme: flowbiteTheme }}>
      <ThemeProvider>
        <App />
      </ThemeProvider>
    </Flowbite>
  </React.StrictMode>
);
