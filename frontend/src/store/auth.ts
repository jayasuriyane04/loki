import { create } from "zustand";
import { api, ApiError } from "@/lib/api";
import type { User } from "@/lib/types";

type AuthState = {
  user: User | null;
  status: "unknown" | "signed-in" | "signed-out";
  bootError: string | null;
  load: () => Promise<void>;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string, name: string) => Promise<void>;
  logout: () => Promise<void>;
  expire: () => void;
};

export const useAuth = create<AuthState>((set) => ({
  user: null,
  status: "unknown",
  bootError: null,
  load: async () => {
    try {
      set({ user: await api.me(), status: "signed-in", bootError: null });
    } catch (e) {
      const offline = e instanceof ApiError && e.status === 0;
      set({ user: null, status: "signed-out", bootError: offline ? e.message : null });
    }
  },
  login: async (email, password) => {
    set({ user: await api.login(email, password), status: "signed-in", bootError: null });
  },
  register: async (email, password, name) => {
    set({ user: await api.register(email, password, name), status: "signed-in", bootError: null });
  },
  logout: async () => {
    await api.logout().catch(() => undefined);
    set({ user: null, status: "signed-out" });
  },
  expire: () => set({ user: null, status: "signed-out" }),
}));
