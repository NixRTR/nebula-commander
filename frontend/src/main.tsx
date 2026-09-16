import React from "react";
import ReactDOM from "react-dom/client";
import { Flowbite } from "flowbite-react";
import App from "./App";
import { ThemeProvider } from "./contexts/ThemeContext";
import { flowbiteTheme } from "./theme/flowbiteTheme";
import { applyThemeCssVars } from "./theme/applyTheme";
import { DEFAULT_THEME } from "./theme/tokens";
import "./index.css";

// Seed the theme CSS vars (primary button color, page/container backgrounds)
// with the defaults before mount, so the Flowbite Button/Card/Navbar/Sidebar
// overrides (which read them via `var(...)`) always have a valid value on
// first paint. ThemeContext overwrites these with the user's saved theme
// shortly after mount once GET /me/theme resolves.
applyThemeCssVars(DEFAULT_THEME);

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

// Flowbite's own <Flowbite> wrapper independently manages the `dark` class via
// its own `flowbite-theme-mode` localStorage key (unrelated to ours). Its
// mount effect prefers whatever is ALREADY in that key over the `mode` prop
// below, so once the two keys disagree even once (e.g. after our own toggle
// updates "theme" but not "flowbite-theme-mode"), Flowbite's stale key wins on
// every subsequent load and silently overrides our class - permanently stuck
// out of sync. Overwriting it here, right before Flowbite mounts, means it
// always reads a fresh value that matches ours instead of a stale one.
localStorage.setItem('flowbite-theme-mode', initialIsDark ? 'dark' : 'light');

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <Flowbite theme={{ mode: initialIsDark ? 'dark' : 'light', theme: flowbiteTheme }}>
      <ThemeProvider>
        <App />
      </ThemeProvider>
    </Flowbite>
  </React.StrictMode>
);
