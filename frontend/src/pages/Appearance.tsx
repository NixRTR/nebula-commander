import { useEffect, useState } from "react";
import { Card, Button, Badge, TextInput } from "flowbite-react";
import { HiRefresh, HiSave, HiTrash, HiCheck, HiDownload } from "react-icons/hi";
import { useTheme } from "../contexts/ThemeContext";
import { useToast } from "../contexts/ToastContext";
import { DEFAULT_THEME, ThemeTokenKey, ThemeTokens, ThemeTokenValue, contrastTextColor } from "../theme/tokens";
import { themeToYaml, downloadTextFile, slugifyFilename } from "../theme/themeYaml";
import { ColorTokenRow } from "../components/settings/ColorTokenRow";
import { listSavedThemes, createSavedTheme, deleteSavedTheme, SavedTheme } from "../api/client";

interface TokenGroup {
  title: string;
  tokens: { key: ThemeTokenKey; label: string }[];
}

const GROUPS: TokenGroup[] = [
  {
    title: "Backgrounds",
    tokens: [
      { key: "background", label: "Page background" },
      { key: "background2", label: "Container background (menus, nav, cards)" },
    ],
  },
  {
    title: "Primary Action",
    tokens: [{ key: "primary", label: "Primary button color" }],
  },
  {
    title: "Node Status",
    tokens: [
      { key: "status.neverActive", label: "Never active" },
      { key: "status.active", label: "Active" },
      { key: "status.inactive", label: "Inactive" },
    ],
  },
  {
    title: "Type / OS Badges",
    tokens: [
      { key: "badge.lighthouse", label: "Lighthouse" },
      { key: "badge.relay", label: "Relay" },
      { key: "badge.ios", label: "iOS" },
      { key: "badge.android", label: "Android" },
      { key: "badge.windows", label: "Windows" },
      { key: "badge.linux", label: "Linux" },
      { key: "badge.macos", label: "macOS" },
      { key: "badge.node", label: "Node (default)" },
    ],
  },
  {
    title: "Group Access Diagram",
    tokens: [
      { key: "group.restricted", label: "Restricted group" },
      { key: "group.open", label: "Open group" },
      { key: "diagram.edge", label: "Edge / arrow" },
    ],
  },
];

export function Appearance() {
  const { theme, isDark, updateTokens, loading } = useTheme();
  const { showToast } = useToast();
  const [edits, setEdits] = useState<ThemeTokens>(theme);
  const [saving, setSaving] = useState(false);
  const [savedThemes, setSavedThemes] = useState<SavedTheme[]>([]);
  const [newThemeName, setNewThemeName] = useState("");
  const [savingTheme, setSavingTheme] = useState(false);
  const [applyingId, setApplyingId] = useState<number | null>(null);
  const [deletingId, setDeletingId] = useState<number | null>(null);

  // Sync local edit state once the real theme has loaded from the server.
  useEffect(() => {
    if (!loading) setEdits(theme);
  }, [loading, theme]);

  useEffect(() => {
    listSavedThemes()
      .then(setSavedThemes)
      .catch(() => {
        // Not fatal - the Saved Themes list just stays empty.
      });
  }, []);

  const setToken = (key: ThemeTokenKey, value: ThemeTokenValue) => {
    setEdits((prev) => ({ ...prev, [key]: value }));
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      await updateTokens(edits);
      showToast("success", "Theme saved", "Your color changes have been saved to your account.");
    } catch {
      showToast("error", "Failed to save theme", "Please try again.");
    } finally {
      setSaving(false);
    }
  };

  const handleReset = () => {
    setEdits(DEFAULT_THEME);
  };

  const handleExportYaml = () => {
    downloadTextFile("nebula-commander-theme.yaml", themeToYaml(edits, "Current theme"));
  };

  const handleExportSavedTheme = (st: SavedTheme) => {
    downloadTextFile(`${slugifyFilename(st.name)}.yaml`, themeToYaml(st.tokens, st.name));
  };

  const handleSaveAsTheme = async () => {
    const name = newThemeName.trim();
    if (!name) return;
    setSavingTheme(true);
    try {
      // Saves whatever is currently in the live-preview edit buffer, independent
      // of whether "Save changes" below has been clicked yet.
      const created = await createSavedTheme(name, edits);
      setSavedThemes((prev) => [...prev, created]);
      setNewThemeName("");
      showToast("success", "Theme saved", `"${created.name}" was added to your saved themes.`);
    } catch (e) {
      showToast("error", "Failed to save theme", e instanceof Error ? e.message : "Please try again.");
    } finally {
      setSavingTheme(false);
    }
  };

  const handleApplyTheme = async (st: SavedTheme) => {
    setApplyingId(st.id);
    try {
      await updateTokens(st.tokens);
      showToast("success", "Theme applied", `"${st.name}" is now your active theme.`);
    } catch {
      showToast("error", "Failed to apply theme", "Please try again.");
    } finally {
      setApplyingId(null);
    }
  };

  const handleDeleteTheme = async (st: SavedTheme) => {
    if (!window.confirm(`Delete saved theme "${st.name}"?`)) return;
    setDeletingId(st.id);
    try {
      await deleteSavedTheme(st.id);
      setSavedThemes((prev) => prev.filter((t) => t.id !== st.id));
    } catch {
      showToast("error", "Failed to delete theme", "Please try again.");
    } finally {
      setDeletingId(null);
    }
  };

  const mode = isDark ? "dark" : "light";
  const previewBg = (key: ThemeTokenKey) => edits[key]?.[mode] ?? DEFAULT_THEME[key][mode];
  const badgeStyle = (key: ThemeTokenKey) => {
    const bg = previewBg(key);
    return { backgroundColor: bg, color: contrastTextColor(bg) };
  };

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold text-[var(--nc-bg2-light-contrast)] dark:text-[var(--nc-bg2-dark-contrast)]">Appearance</h1>
      <p className="text-sm text-gray-600 dark:text-gray-400">
        Customize the colors used across Nebula Commander. Changes are saved to your account and
        apply to both light and dark mode - you're currently editing in{" "}
        <strong>{mode}</strong> mode preview below (toggle the moon/sun icon in the navbar to see
        the other mode).
      </p>

      <Card>
        <h2 className="text-lg font-semibold text-[var(--nc-bg2-light-contrast)] dark:text-[var(--nc-bg2-dark-contrast)] mb-2">Live preview</h2>
        <div className="flex flex-wrap items-center gap-3">
          <Button color="purple">Primary button</Button>
          <span
            className="inline-block rounded-lg border border-gray-200 dark:border-gray-700 px-4 py-2 text-sm"
            style={{ backgroundColor: previewBg("status.active") }}
          >
            Active node
          </span>
          <span
            className="inline-block rounded-lg border border-gray-200 dark:border-gray-700 px-4 py-2 text-sm"
            style={{ backgroundColor: previewBg("status.inactive") }}
          >
            Inactive node
          </span>
          <span
            className="inline-block rounded-lg border border-gray-200 dark:border-gray-700 px-4 py-2 text-sm"
            style={{ backgroundColor: previewBg("status.neverActive") }}
          >
            Never active
          </span>
          <Badge size="sm" style={badgeStyle("badge.lighthouse")}>Lighthouse</Badge>
          <Badge size="sm" style={badgeStyle("badge.relay")}>Relay</Badge>
          <Badge size="sm" style={badgeStyle("badge.windows")}>Windows</Badge>
        </div>
      </Card>

      <Card>
        <h2 className="text-lg font-semibold text-[var(--nc-bg2-light-contrast)] dark:text-[var(--nc-bg2-dark-contrast)] mb-1">Saved Themes</h2>
        <p className="text-sm text-gray-600 dark:text-gray-400 mb-3">
          Save your current color choices below as a named theme you can switch back to later.
        </p>
        <div className="flex flex-wrap gap-2 mb-3">
          <TextInput
            value={newThemeName}
            onChange={(e) => setNewThemeName(e.target.value)}
            placeholder="Theme name"
            className="min-w-0 flex-1"
          />
          <Button
            color="purple"
            onClick={handleSaveAsTheme}
            isProcessing={savingTheme}
            disabled={savingTheme || !newThemeName.trim()}
          >
            Save current as...
          </Button>
        </div>
        {savedThemes.length === 0 ? (
          <p className="text-sm text-gray-400 dark:text-gray-500">No saved themes yet.</p>
        ) : (
          <div className="divide-y divide-gray-100 dark:divide-gray-700">
            {savedThemes.map((st) => (
              <div key={st.id} className="flex items-center justify-between gap-2 py-2">
                <span className="text-sm text-[var(--nc-bg2-light-contrast)] dark:text-[var(--nc-bg2-dark-contrast)] truncate">{st.name}</span>
                <div className="flex gap-2 shrink-0">
                  <Button
                    size="xs"
                    color="purple"
                    onClick={() => handleApplyTheme(st)}
                    isProcessing={applyingId === st.id}
                    disabled={applyingId === st.id}
                  >
                    <HiCheck className="w-3.5 h-3.5 mr-1" />
                    Apply
                  </Button>
                  <Button size="xs" color="gray" onClick={() => handleExportSavedTheme(st)}>
                    <HiDownload className="w-3.5 h-3.5" />
                  </Button>
                  <Button
                    size="xs"
                    color="gray"
                    onClick={() => handleDeleteTheme(st)}
                    isProcessing={deletingId === st.id}
                    disabled={deletingId === st.id}
                  >
                    <HiTrash className="w-3.5 h-3.5" />
                  </Button>
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>

      {GROUPS.map((group) => (
        <Card key={group.title}>
          <h2 className="text-lg font-semibold text-[var(--nc-bg2-light-contrast)] dark:text-[var(--nc-bg2-dark-contrast)] mb-1">{group.title}</h2>
          <div className="divide-y divide-gray-100 dark:divide-gray-700">
            {group.tokens.map(({ key, label }) => (
              <ColorTokenRow
                key={key}
                label={label}
                value={edits[key] ?? DEFAULT_THEME[key]}
                onChange={(value) => setToken(key, value)}
              />
            ))}
          </div>
        </Card>
      ))}

      <div className="flex flex-wrap gap-2">
        <Button color="purple" onClick={handleSave} isProcessing={saving} disabled={saving}>
          <HiSave className="w-4 h-4 mr-1" />
          Save changes
        </Button>
        <Button color="gray" onClick={handleReset} disabled={saving}>
          <HiRefresh className="w-4 h-4 mr-1" />
          Reset to defaults
        </Button>
        <Button color="gray" onClick={handleExportYaml}>
          <HiDownload className="w-4 h-4 mr-1" />
          Export YAML
        </Button>
      </div>
    </div>
  );
}
