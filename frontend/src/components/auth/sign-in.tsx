"use client";

import { useState } from "react";
import { signIn } from "../../lib/auth-client";
import { useRouter } from "next/navigation";

export function SignIn() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");
  const router = useRouter();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setMessage("");

    const response = await signIn.email({
      email,
      password,
    });

    if (response.error) {
      setMessage(response.error.message || "Failed to sign in");
      setLoading(false);
      return;
    }

    setMessage("Signed in successfully!");
    setLoading(false);

    setTimeout(() => {
      router.push("/dashboard");
      router.refresh();
    }, 500);
  };

  const inputStyle: React.CSSProperties = {
    background: "rgba(255,255,255,0.02)",
    color: "var(--fg-2)",
    border: "1px solid var(--border)",
    borderRadius: "var(--radius-sm)",
    padding: "12px 14px",
    fontFamily: "var(--font-body)",
    fontSize: "var(--text-base)",
    fontFeatureSettings: '"cv01", "ss03"',
    outline: "none",
    transition: "border-color var(--motion-fast) var(--ease-standard)",
    width: "100%",
  };

  return (
    <div
      style={{
        background: "var(--surface)",
        border: "1px solid var(--border)",
        borderRadius: "var(--radius-md)",
        padding: "var(--space-6)",
      }}
    >
      <div style={{ marginBottom: "var(--space-4)" }}>
        <h2
          className="text-lg font-semibold"
          style={{ color: "var(--fg)", fontWeight: 510, fontFeatureSettings: '"cv01", "ss03"' }}
        >
          Sign In
        </h2>
        <p className="text-sm" style={{ color: "var(--meta)" }}>
          Sign in to your account
        </p>
      </div>

      <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: "var(--space-4)" }}>
        <input
          type="email"
          placeholder="Email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
          disabled={loading}
          style={inputStyle}
          onFocus={(e) => (e.currentTarget.style.borderColor = "var(--accent)")}
          onBlur={(e) => (e.currentTarget.style.borderColor = "var(--border)")}
        />
        <input
          type="password"
          placeholder="Password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
          disabled={loading}
          style={inputStyle}
          onFocus={(e) => (e.currentTarget.style.borderColor = "var(--accent)")}
          onBlur={(e) => (e.currentTarget.style.borderColor = "var(--border)")}
        />
        <button
          type="submit"
          disabled={loading}
          style={{
            display: "inline-flex",
            alignItems: "center",
            justifyContent: "center",
            gap: "var(--space-2)",
            padding: "10px 20px",
            borderRadius: "var(--radius-sm)",
            fontFamily: "var(--font-display)",
            fontSize: "var(--text-sm)",
            fontWeight: 510,
            fontFeatureSettings: '"cv01", "ss03"',
            lineHeight: 1,
            cursor: loading ? "not-allowed" : "pointer",
            border: "1px solid transparent",
            background: "var(--accent)",
            color: "#ffffff",
            width: "100%",
            opacity: loading ? 0.45 : 1,
            transition: "background-color var(--motion-fast) var(--ease-standard)",
          }}
          onMouseEnter={(e) => {
            if (!loading) e.currentTarget.style.background = "var(--accent-hover)";
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.background = "var(--accent)";
          }}
        >
          {loading ? "Signing In..." : "Sign In"}
        </button>
      </form>

      {message && (
        <p
          className="text-sm mt-4"
          style={{
            color: message.includes("successfully") ? "var(--success)" : "var(--danger)",
          }}
        >
          {message}
        </p>
      )}
    </div>
  );
}
