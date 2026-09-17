import { ThemeTokenKey, ThemeTokens } from "./tokens";

/**
 * Serializes theme tokens to a small, hand-rolled YAML document - no library
 * needed since this shape is always a flat map of token-key -> {light, dark}
 * hex strings, with no lists, nesting, or characters that need escaping
 * beyond quoting the hex values (unquoted, a leading "#" would be parsed as a
 * YAML comment instead of a value).
 */
export function themeToYaml(tokens: ThemeTokens, name?: string): string {
  const lines: string[] = ["# Nebula Commander theme export"];
  if (name) lines.push(`# Name: ${name}`);
  lines.push(`# Exported: ${new Date().toISOString()}`, "");

  for (const key of Object.keys(tokens) as ThemeTokenKey[]) {
    const value = tokens[key];
    lines.push(`${key}:`, `  light: "${value.light}"`, `  dark: "${value.dark}"`);
  }
  return lines.join("\n") + "\n";
}

/** Triggers a browser download of the given text content as a file. */
export function downloadTextFile(filename: string, content: string, mimeType = "text/yaml"): void {
  const blob = new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

/** Turns a theme/user-entered name into a filesystem-safe filename stem. */
export function slugifyFilename(name: string): string {
  return (
    name
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/(^-|-$)/g, "") || "theme"
  );
}
