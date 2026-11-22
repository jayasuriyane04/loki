"use client";

import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useState } from "react";
import { useAuth } from "@/store/auth";
import { useChat } from "@/store/chat";
import { AssistantView } from "./AssistantView";
import { KnowledgeBase } from "./KnowledgeBase";
import { MemoryManager } from "./MemoryManager";
import { SidePanel } from "./SidePanel";
import { TopBar } from "./TopBar";

export function AppShell() {
  const expire = useAuth((s) => s.expire);
  const [drawer, setDrawer] = useState(false);
  const view = useChat((s) => s.view);

  useEffect(() => {
    const chat = useChat.getState();
    chat.connect(expire);
    chat.refreshConversations();
    chat.refreshModels();
    chat.refreshVoice();
    const t = setInterval(() => useChat.getState().refreshModels(), 60_000);
    // Speech models load in the background after the server starts; poll until they settle.
    const v = setInterval(() => {
      const vs = useChat.getState().voiceStatus;
      if (!vs || vs.stt.state === "loading" || vs.tts.state === "loading") useChat.getState().refreshVoice();
    }, 3_000);
    return () => {
      clearInterval(t);
      clearInterval(v);
      useChat.getState().reset();
    };
  }, [expire]);

  return (
    <div className="flex h-full flex-col">
      <TopBar onMenu={() => setDrawer(true)} />
      <div className="flex min-h-0 flex-1">
        <aside className="hidden w-72 shrink-0 border-r border-line bg-night/40 lg:block">
          <SidePanel />
        </aside>
        <main className="min-w-0 flex-1">
          {view === "memories" ? <MemoryManager /> : view === "knowledge" ? <KnowledgeBase /> : <AssistantView />}
        </main>
      </div>

      <AnimatePresence>
        {drawer && (
          <>
            <motion.div
              className="fixed inset-0 z-30 bg-black/60 lg:hidden"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              onClick={() => setDrawer(false)}
            />
            <motion.aside
              className="fixed inset-y-0 left-0 z-40 w-[85vw] max-w-80 border-r border-line bg-night lg:hidden"
              initial={{ x: "-100%" }}
              animate={{ x: 0 }}
              exit={{ x: "-100%" }}
              transition={{ type: "tween", duration: 0.22 }}
            >
              <SidePanel onNavigate={() => setDrawer(false)} />
            </motion.aside>
          </>
        )}
      </AnimatePresence>
    </div>
  );
}
