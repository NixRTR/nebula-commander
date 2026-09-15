import { useEffect, useState } from "react";
import { Card, Button, Badge } from "flowbite-react";
import { HiRefresh, HiSave } from "react-icons/hi";
import { useTheme } from "../contexts/ThemeContext";
import { useToast } from "../contexts/ToastContext";
import { DEFAULT_THEME, ThemeTokenKey, ThemeTokens, ThemeTokenValue, contrastTextColor } from "../theme/tokens";
import { ColorTokenRow } from "../components/settings/ColorTokenRow";

interface TokenGroup {
  title: string;
  tokens: { key: ThemeTokenKey; label: string }[];
}

const GROUPS: TokenGroup[] = [
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

  // Sync local edit state once the real theme has loaded from the server.
  useEffect(() => {
    if (!loading) setEdits(theme);
  }, [loading, theme]);

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

  const mode = isDark ? "dark" : "light";
  const previewBg = (key: ThemeTokenKey) => edits[key]?.[mode] ?? DEFAULT_THEME[key][mode];
  const badgeStyle = (key: ThemeTokenKey) => {
    const bg = previewBg(key);
    return { backgroundColor: bg, color: contrastTextColor(bg) };
  };

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold text-gray-900 dark:text-white">Appearance</h1>
      <p className="text-sm text-gray-600 dark:text-gray-400">
        Customize the colors used across Nebula Commander. Changes are saved to your account and
        apply to both light and dark mode - you're currently editing in{" "}
        <strong>{mode}</strong> mode preview below (toggle the moon/sun icon in the navbar to see
        the other mode).
      </p>

      <Card>
        <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-2">Live preview</h2>
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

      {GROUPS.map((group) => (
        <Card key={group.title}>
          <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-1">{group.title}</h2>
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
      </div>
    </div>
  );
}
