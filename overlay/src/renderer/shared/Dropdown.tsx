import { useEffect, useRef, useState } from "react";
import "./dropdown.css";

export interface DropdownOption<T extends string> {
  value: T;
  label: string;
}

interface DropdownProps<T extends string> {
  /** Names the list for screen readers, since the heading above it isn't its label. */
  label: string;
  value: T | null | undefined;
  options: readonly DropdownOption<T>[];
  onChange(value: T): void;
}

/**
 * Built from buttons rather than a native select: the overlay window can't take focus, and a
 * select's popup needs it, so a native one would either fail to open or take the keyboard from
 * the game.
 */
export function Dropdown<T extends string>({
  label,
  value,
  options,
  onChange,
}: DropdownProps<T>) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const current = options.find((option) => option.value === value);

  // Clicks on the game never reach the overlay's document, so there the menu stays open until
  // the player picks or clicks the trigger again. In the Control Center any outside click closes it.
  useEffect(() => {
    if (!open) return;
    const close = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("pointerdown", close);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("pointerdown", close);
      document.removeEventListener("keydown", escape);
    };
  }, [open]);

  return (
    <div className="dropdown" ref={root}>
      <button
        className="option dropdown-trigger"
        type="button"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={`${label}: ${current?.label ?? "not set"}`}
        onClick={() => setOpen((was) => !was)}
      >
        <span className="dropdown-value">{current?.label ?? "Choose"}</span>
        <span className="dropdown-chevron" aria-hidden />
      </button>
      {open && (
        <div className="dropdown-menu" role="listbox" aria-label={label}>
          {options.map((option) => (
            <button
              key={option.value}
              className="dropdown-item"
              type="button"
              role="option"
              aria-selected={option.value === value}
              onClick={() => {
                setOpen(false);
                if (option.value !== value) onChange(option.value);
              }}
            >
              {option.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
