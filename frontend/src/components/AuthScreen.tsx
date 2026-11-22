"use client";

import { motion } from "framer-motion";
import { useState } from "react";
import { useAuth } from "@/store/auth";
import { Visualizer } from "./Visualizer";

export function AuthScreen() {
  const { login, register, bootError } = useAuth();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      if (mode === "login") await login(email, password);
      else await register(email, password, name);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSubmitting(false);
    }
  }

  const input =
    "w-full rounded-lg bg-night/80 border border-line px-3.5 py-2.5 text-[15px] text-ink placeholder:text-faint outline-none focus:border-cyan/50 focus:ring-2 focus:ring-cyan/10 transition";

  return (
    <main className="flex h-full items-center justify-center overflow-y-auto px-4 py-10">
      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5, ease: "easeOut" }}
        className="w-full max-w-sm"
      >
        <div className="flex flex-col items-center">
          <Visualizer state="idle" size={150} />
          <h1 className="-mt-2 font-mono text-2xl tracking-[0.5em] pl-[0.5em] text-ink">LOKI</h1>
          <p className="mt-2 text-sm text-dim">Your personal AI assistant</p>
        </div>

        <form onSubmit={submit} className="glass mt-8 space-y-3 rounded-2xl p-6">
          <div className="hud-label mb-1">{mode === "login" ? "Sign in" : "Create account"}</div>
          {mode === "register" && (
            <input
              className={input}
              placeholder="What should LOKI call you?"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
              maxLength={100}
              autoComplete="nickname"
            />
          )}
          <input
            className={input}
            type="email"
            placeholder="Email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            autoComplete="email"
          />
          <input
            className={input}
            type="password"
            placeholder={mode === "register" ? "Password (10+ characters)" : "Password"}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            minLength={mode === "register" ? 10 : 1}
            autoComplete={mode === "login" ? "current-password" : "new-password"}
          />
          {(error || bootError) && (
            <p role="alert" className="text-sm text-bad">
              {error ?? bootError}
            </p>
          )}
          <button
            type="submit"
            disabled={submitting}
            className="w-full rounded-lg bg-cyan/90 py-2.5 text-[15px] font-medium text-void transition hover:bg-cyan disabled:opacity-50"
          >
            {submitting ? "…" : mode === "login" ? "Sign in" : "Create account"}
          </button>
          <button
            type="button"
            onClick={() => {
              setMode(mode === "login" ? "register" : "login");
              setError(null);
            }}
            className="w-full pt-1 text-sm text-dim transition hover:text-ink"
          >
            {mode === "login" ? "New here? Create an account" : "Have an account? Sign in"}
          </button>
        </form>
      </motion.div>
    </main>
  );
}
