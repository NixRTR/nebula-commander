import { useRef, useState, useCallback, useEffect } from "react";
import { HiX } from "react-icons/hi";

interface GroupsTagInputProps {
  value: string[];
  onChange: (value: string[]) => void;
  placeholder?: string;
  disabled?: boolean;
  suggestions?: string[];
  id?: string;
  "data-testid"?: string;
}

export function GroupsTagInput({
  value,
  onChange,
  placeholder = "Type a group and press Enter",
  disabled = false,
  suggestions = [],
  id,
  "data-testid": dataTestId,
}: GroupsTagInputProps) {
  const [inputValue, setInputValue] = useState("");
  const [showSuggestions, setShowSuggestions] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  const addTag = useCallback(
    (tag: string) => {
      const trimmed = tag.trim();
      if (!trimmed || value.includes(trimmed)) return;
      onChange([...value, trimmed]);
      setInputValue("");
    },
    [value, onChange]
  );

  const removeTag = useCallback(
    (index: number) => {
      onChange(value.filter((_, i) => i !== index));
    },
    [value, onChange]
  );

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLInputElement>) => {
      if (e.key === "Enter") {
        e.preventDefault();
        addTag(inputValue);
      } else if (e.key === "Backspace" && !inputValue && value.length > 0) {
        removeTag(value.length - 1);
      }
    },
    [inputValue, addTag, removeTag, value.length]
  );

  const filteredSuggestions = suggestions.filter(
    (s) => s && !value.includes(s) && (!inputValue.trim() || s.toLowerCase().includes(inputValue.trim().toLowerCase()))
  );

  useEffect(() => {
    if (!showSuggestions) return;
    const handleClickOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setShowSuggestions(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [showSuggestions]);

  return (
    <div className="relative min-w-0 w-full" ref={containerRef}>
      <div
        className={`flex flex-wrap gap-2 items-center p-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-gray-50 dark:bg-gray-700 focus-within:ring-2 focus-within:ring-purple-500 focus-within:border-purple-500 ${
          disabled ? "opacity-60 cursor-not-allowed" : ""
        }`}
        onClick={() => !disabled && inputRef.current?.focus()}
      >
        {value.map((tag, idx) => (
          <span
            key={`${tag}-${idx}`}
            className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-sm bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-200"
          >
            {tag}
            {!disabled && (
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  removeTag(idx);
                }}
                className="hover:bg-purple-200 dark:hover:bg-purple-800 rounded p-0.5"
                aria-label={`Remove ${tag}`}
              >
                <HiX className="w-4 h-4" />
              </button>
            )}
          </span>
        ))}
        <input
          id={id}
          data-testid={dataTestId}
          type="text"
          value={inputValue}
          onChange={(e) => setInputValue(e.target.value)}
          onKeyDown={handleKeyDown}
          onFocus={() => setShowSuggestions(true)}
          disabled={disabled}
          placeholder={value.length === 0 ? placeholder : ""}
          className="flex-1 min-w-[120px] py-1 px-0 bg-transparent border-none focus:ring-0 focus:outline-none text-gray-900 dark:text-white placeholder-gray-500 dark:placeholder-gray-400"
        />
      </div>
      {showSuggestions && filteredSuggestions.length > 0 && !disabled && (
        <ul
          className="absolute z-10 mt-1 w-full max-h-40 overflow-auto rounded-lg border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-800 shadow-lg"
          role="listbox"
        >
          {filteredSuggestions.slice(0, 15).map((s) => (
            <li
              key={s}
              role="option"
              className="px-3 py-2 cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-900 dark:text-white text-sm"
              onMouseDown={(e) => {
                e.preventDefault();
                addTag(s);
                setShowSuggestions(false);
              }}
            >
              {s}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
