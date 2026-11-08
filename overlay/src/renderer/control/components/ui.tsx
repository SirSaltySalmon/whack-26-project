/* Small form pieces shared by the tabs, so every tab looks the same without a UI library. */
import type { ReactNode } from "react";

export function Section({
  title,
  hint,
  children,
  aside,
  className,
}: {
  title: string;
  hint?: ReactNode;
  children: ReactNode;
  aside?: ReactNode;
  className?: string;
}) {
  return (
    <section className={className ? `cc-section ${className}` : "cc-section"}>
      <header className="cc-section-head">
        <div>
          <h2>{title}</h2>
          {hint && <p className="cc-hint">{hint}</p>}
        </div>
        {aside}
      </header>
      {children}
    </section>
  );
}

export function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: ReactNode;
  children: ReactNode;
}) {
  return (
    <label className="cc-field">
      <span className="cc-field-label">{label}</span>
      {children}
      {hint && <span className="cc-hint">{hint}</span>}
    </label>
  );
}

export function TextInput({
  value,
  onChange,
  placeholder,
  type = "text",
  disabled,
}: {
  value: string;
  onChange(value: string): void;
  placeholder?: string;
  type?: "text" | "password" | "number";
  disabled?: boolean;
}) {
  return (
    <input
      className="cc-input"
      type={type}
      value={value}
      placeholder={placeholder}
      disabled={disabled}
      spellCheck={false}
      autoComplete="off"
      onChange={(event) => onChange(event.target.value)}
    />
  );
}

export function Toggle({
  label,
  hint,
  on,
  onChange,
  disabled,
}: {
  label: string;
  hint?: ReactNode;
  on: boolean;
  onChange(on: boolean): void;
  disabled?: boolean;
}) {
  return (
    <label className={`cc-toggle${disabled ? " cc-disabled" : ""}`}>
      <input
        type="checkbox"
        checked={on}
        disabled={disabled}
        onChange={(event) => onChange(event.target.checked)}
      />
      <span className="cc-switch" aria-hidden />
      <span>
        <span className="cc-toggle-label">{label}</span>
        {hint && <span className="cc-hint">{hint}</span>}
      </span>
    </label>
  );
}

export function Pill({
  tone,
  children,
  title,
}: {
  tone: "on" | "off" | "warn" | "info" | "player" | "observed" | "wiki";
  children: ReactNode;
  title?: string;
}) {
  return (
    <span className={`cc-pill cc-pill-${tone}`} title={title}>
      {children}
    </span>
  );
}

export function Notice({
  tone = "info",
  children,
}: {
  tone?: "info" | "warn";
  children: ReactNode;
}) {
  return <div className={`cc-notice cc-notice-${tone}`}>{children}</div>;
}
