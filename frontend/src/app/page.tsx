"use client";

import { useEffect } from "react";
import { AppShell } from "@/components/AppShell";
import { AuthScreen } from "@/components/AuthScreen";
import { useAuth } from "@/store/auth";

export default function Home() {
  const status = useAuth((s) => s.status);

  useEffect(() => {
    useAuth.getState().load();
  }, []);

  if (status === "unknown") {
    return (
      <div className="flex h-full items-center justify-center">
        <span className="hud-label">Initialising LOKI</span>
      </div>
    );
  }
  return status === "signed-in" ? <AppShell /> : <AuthScreen />;
}
