"use client";

import { useState, type ReactNode, type InputHTMLAttributes } from "react";

/* ─────────────────────────────────────────────
   Input — Linear App Design System (exact from repo)
   Source: https://github.com/nexu-io/open-design/blob/main/design-systems/linear-app/components.html
   ───────────────────────────────────────────── */

type InputSize = "sm" | "md";

interface InputProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "size"> {
  label?: string;
  error?: string;
  inputSize?: InputSize;
  leftIcon?: ReactNode;
}

export function Input({
  label,
  error,
  inputSize = "md",
  leftIcon,
  placeholder,
  style,
  onFocus,
  onBlur,
  ...rest
}: InputProps) {
  const [focused, setFocused] = useState(false);

  const inputStyle: React.CSSProperties = {
    background: "rgba(255,255,255,0.02)",
    color: "var(--fg-2)",
    border: `1px solid ${focused ? "var(--accent)" : "var(--border)"}`,
    borderRadius: "var(--radius-sm)",
    fontFamily: "var(--font-body)",
    fontSize: inputSize === "sm" ? "var(--text-sm)" : "var(--text-base)",
    fontFeatureSettings: '"cv01", "ss03"',
    outline: "none",
    transition: "border-color var(--motion-fast) var(--ease-standard)",
    width: "100%",
    ...(inputSize === "sm"
      ? { padding: "8px 12px" }
      : { padding: "12px 14px" }),
    ...(leftIcon ? { paddingLeft: 36 } : {}),
    ...style,
  };

  const handleFocus = (e: React.FocusEvent<HTMLInputElement>) => {
    setFocused(true);
    onFocus?.(e);
  };

  const handleBlur = (e: React.FocusEvent<HTMLInputElement>) => {
    setFocused(false);
    onBlur?.(e);
  };

  return (
    <div className="field" style={{ display: "flex", flexDirection: "column", gap: "var(--space-2)" }}>
      {label && (
        <label
          style={{
            fontSize: "var(--text-sm)",
            fontWeight: 510,
            color: "var(--fg-2)",
            fontFeatureSettings: '"cv01", "ss03"',
          }}
        >
          {label}
        </label>
      )}
      <div style={{ position: "relative" }}>
        {leftIcon && (
          <span
            style={{
              position: "absolute",
              left: 12,
              top: "50%",
              transform: "translateY(-50%)",
              color: "var(--meta)",
              pointerEvents: "none",
              display: "flex",
            }}
          >
            {leftIcon}
          </span>
        )}
        <input
          style={inputStyle}
          placeholder={placeholder}
          onFocus={handleFocus}
          onBlur={handleBlur}
          {...rest}
        />
      </div>
      {error && (
        <p
          style={{
            fontSize: "var(--text-xs)",
            color: "var(--danger)",
            margin: 0,
            animation: "fadeIn 150ms ease-out",
          }}
        >
          {error}
        </p>
      )}
    </div>
  );
}
