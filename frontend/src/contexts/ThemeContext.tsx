import React, { createContext, useContext, useState, useEffect, useCallback, ReactNode } from "react";
import { apiClient } from "../api/client";
import { DEFAULT_THEME, ThemeTokenKey, ThemeTokens, ThemeTokenValue } from "../theme/tokens";
import { applyPrimaryColor } from "../theme/applyTheme";

interface ThemeContextType {
  isDark: boolean;
  toggleDark: () => void;
  theme: ThemeTokens;
  resolve: (key: ThemeTokenKey) => string;
  updateTokens: (updates: Partial<Record<ThemeTokenKey, ThemeTokenValue>>) => Promise<void>;
  resetToDefaults: () => void;
  loading: boolean;
}

const ThemeContext = createContext<ThemeContextType | undefined>(undefined);

// eslint-disable-next-line react-refresh/only-export-components
export const useTheme = () => {
  const context = useContext(ThemeContext);
  if (!context) {
    throw new Error("useTheme must be used within a ThemeProvider");
  }
  return context;
};

interface ThemeProviderProps {
  children: ReactNode;
}

export const ThemeProvider: React.FC<ThemeProviderProps> = ({ children }) => {
  // main.tsx already set the `dark` class on <html> before React mounted -
  // read it back rather than re-deciding from localStorage, so this can't
  // disagree with what's already painted on screen.
  const [isDark, setIsDark] = useState(() =>
    document.documentElement.classList.contains("dark")
  );
  const [theme, setTheme] = useState<ThemeTokens>(DEFAULT_THEME);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    applyPrimaryColor(theme);
  }, [theme]);

  useEffect(() => {
    let cancelled = false;
    apiClient
      .get("/users/me/theme")
      .then((res) => {
        if (!cancelled && res.data?.theme) {
          setTheme(res.data.theme);
        }
      })
      .catch(() => {
        // Not authenticated yet, or request failed - fall back to defaults.
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const toggleDark = useCallback(() => {
    setIsDark((prev) => {
      const next = !prev;
      if (next) {
        document.documentElement.classList.add("dark");
        localStorage.setItem("theme", "dark");
      } else {
        document.documentElement.classList.remove("dark");
        localStorage.setItem("theme", "light");
      }
      return next;
    });
  }, []);

  const resolve = useCallback(
    (key: ThemeTokenKey): string => {
      const value = theme[key] ?? DEFAULT_THEME[key];
      return isDark ? value.dark : value.light;
    },
    [theme, isDark]
  );

  const updateTokens = useCallback(
    async (updates: Partial<Record<ThemeTokenKey, ThemeTokenValue>>) => {
      const res = await apiClient.put("/users/me/theme", { theme: updates });
      if (res.data?.theme) {
        setTheme(res.data.theme);
      }
    },
    []
  );

  const resetToDefaults = useCallback(() => {
    setTheme(DEFAULT_THEME);
  }, []);

  return (
    <ThemeContext.Provider
      value={{ isDark, toggleDark, theme, resolve, updateTokens, resetToDefaults, loading }}
    >
      {children}
    </ThemeContext.Provider>
  );
};
