import { ThemeTokenValue } from "../../theme/tokens";

interface ColorTokenRowProps {
  label: string;
  value: ThemeTokenValue;
  onChange: (value: ThemeTokenValue) => void;
}

/** One themeable token: a label plus a light-mode and dark-mode color picker. */
export function ColorTokenRow({ label, value, onChange }: ColorTokenRowProps) {
  return (
    <div className="flex items-center justify-between gap-4 py-2">
      <span className="text-sm text-gray-900 dark:text-white">{label}</span>
      <div className="flex items-center gap-4">
        <label className="flex items-center gap-2 text-xs text-gray-500 dark:text-gray-400">
          Light
          <input
            type="color"
            value={value.light}
            onChange={(e) => onChange({ ...value, light: e.target.value })}
            className="h-8 w-10 rounded border border-gray-300 dark:border-gray-600 cursor-pointer bg-transparent p-0.5"
            aria-label={`${label} light mode color`}
          />
          <span className="font-mono w-16">{value.light}</span>
        </label>
        <label className="flex items-center gap-2 text-xs text-gray-500 dark:text-gray-400">
          Dark
          <input
            type="color"
            value={value.dark}
            onChange={(e) => onChange({ ...value, dark: e.target.value })}
            className="h-8 w-10 rounded border border-gray-300 dark:border-gray-600 cursor-pointer bg-transparent p-0.5"
            aria-label={`${label} dark mode color`}
          />
          <span className="font-mono w-16">{value.dark}</span>
        </label>
      </div>
    </div>
  );
}
