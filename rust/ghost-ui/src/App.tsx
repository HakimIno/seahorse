import { useState, useEffect } from "react";
import { listen } from "@tauri-apps/api/event";
import { invoke } from "@tauri-apps/api/core";
import { motion, AnimatePresence } from "framer-motion";
import { Ghost, Wifi, Cpu, Users, Zap, Terminal, Sparkles, Play, X } from "lucide-react";
import "./App.css";

interface ActivityLog {
  peerId: string;
  context: string;
  timestamp: number;
}

interface Suggestion {
  id: string;
  suggestion: string;
  reason: string;
  priority: number;
  action_id: string;
  data: any;
  timestamp: number;
}

function App() {
  const [peerId, setPeerId] = useState<string>("Initializing...");
  const [localContext, setLocalContext] = useState<string>("Reading OS context...");
  const [peers, setPeers] = useState<string[]>([]);
  const [globalLogs, setGlobalLogs] = useState<ActivityLog[]>([]);
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);

  useEffect(() => {
    const unlisten = listen<string>("ghost-event", (event) => {
      const msg = event.payload;

      if (msg.startsWith("START:")) {
        setPeerId(msg.substring(6));
      } else if (msg.startsWith("LOCAL_CONTEXT:")) {
        setLocalContext(msg.substring(14));
      } else if (msg.startsWith("PEER:")) {
        const id = msg.substring(5);
        setPeers(prev => prev.includes(id) ? prev : [...prev, id]);
      } else if (msg.startsWith("GLOBAL_CONTEXT:")) {
        const parts = msg.substring(15).split(":");
        const pId = parts[0];
        const ctx = parts.slice(1).join(":");

        if (ctx.startsWith("SUGGESTION:")) {
          try {
            const data = JSON.parse(ctx.substring(11));
            setSuggestions(prev => [{ ...data, id: Math.random().toString(), timestamp: Date.now() }, ...prev].slice(0, 3));
          } catch (e) {
            console.error("Failed to parse suggestion", e);
          }
        } else {
          setGlobalLogs(prev => [{ peerId: pId, context: ctx, timestamp: Date.now() }, ...prev].slice(0, 10));
        }
      } else if (msg.startsWith("RECEIVED_COMMAND:")) {
        setGlobalLogs(prev => [{ peerId: "SYSTEM", context: `⚡ Executing: ${msg.split(":")[2]}`, timestamp: Date.now() }, ...prev].slice(0, 10));
      }
    });

    return () => {
      unlisten.then(f => f());
    };
  }, []);

  const handleExecute = async (suggestion: Suggestion) => {
    try {
      await invoke("send_ghost_command", {
        cmd: `EXECUTE:${JSON.stringify({ action_id: suggestion.action_id, suggestion: suggestion.suggestion })}`
      });
      setSuggestions(prev => prev.filter(s => s.id !== suggestion.id));
    } catch (e) {
      console.error("Failed to send command", e);
    }
  };

  return (
    <div className="container">
      <header className="title-bar">
        <div style={{ display: "flex", alignItems: "center", gap: "1rem" }}>
          <div className="glass-card" style={{ padding: "0.5rem", borderRadius: "1rem" }}>
            <Ghost color="#818cf8" size={32} />
          </div>
          <div>
            <h1 style={{ margin: 0, fontSize: "1.25rem" }}>Ghost Node</h1>
            <code style={{ fontSize: "0.7rem", color: "#6366f1" }}>{peerId}</code>
          </div>
        </div>
        <div className="badge">
          <Wifi size={12} style={{ marginRight: "0.5rem" }} />
          P2P Active
        </div>
      </header>

      <div className="dashboard-grid">
        <div style={{ display: "flex", flexDirection: "column", gap: "1.5rem" }}>

          <section className="glass-card proactive-hints">
            <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", color: "#818cf8", marginBottom: "1rem" }}>
              <Sparkles size={16} />
              <span>AI Proactive Hints</span>
            </div>
            <div className="suggestions-list" style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
              <AnimatePresence>
                {suggestions.map((s) => (
                  <motion.div
                    key={s.id}
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, scale: 0.95 }}
                    className="suggestion-card"
                  >
                    <div style={{ flex: 1 }}>
                      <div className="suggestion-text">{s.suggestion}</div>
                      <div className="suggestion-reason">{s.reason}</div>
                    </div>
                    <div style={{ display: "flex", gap: "0.5rem" }}>
                      <button
                        onClick={() => handleExecute(s)}
                        className="action-btn execute"
                      >
                        <Play size={14} />
                      </button>
                      <button
                        onClick={() => setSuggestions(prev => prev.filter(item => item.id !== s.id))}
                        className="action-btn dismiss"
                      >
                        <X size={14} />
                      </button>
                    </div>
                  </motion.div>
                ))}
              </AnimatePresence>
              {suggestions.length === 0 && (
                <div style={{ color: "#4b5563", fontSize: "0.8rem", textAlign: "center", padding: "1rem" }}>
                  AI is observing... No immediate suggestions.
                </div>
              )}
            </div>
          </section>

          <section className="glass-card active-context">
            <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", color: "#9ca3af", marginBottom: "0.5rem" }}>
              <Zap size={16} />
              <span>Current Activity</span>
            </div>
            <div className="context-title">{localContext.split(" (")[0]}</div>
            <div className="context-subtitle">{localContext.includes("(") ? localContext.split(" (")[1].replace(")", "") : "Detecting..."}</div>
          </section>

          <section className="glass-card" style={{ flex: 1, display: "flex", flexDirection: "column" }}>
            <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", color: "#9ca3af", marginBottom: "1rem" }}>
              <Terminal size={16} />
              <span>Global P2P Stream</span>
            </div>
            <div className="global-stream">
              <AnimatePresence>
                {globalLogs.map((log, i) => (
                  <motion.div
                    key={log.timestamp}
                    initial={{ opacity: 0, x: -10 }}
                    animate={{ opacity: 1, x: 0 }}
                    className="stream-item"
                  >
                    <div style={{ color: "#818cf8", fontSize: "0.7rem" }}>
                      {log.peerId === "SYSTEM" ? "⚡ SYSTEM" : `Peer ..${log.peerId.slice(-6)}`}
                    </div>
                    <div>{log.context}</div>
                  </motion.div>
                ))}
              </AnimatePresence>
            </div>
          </section>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: "1.5rem" }}>
          <section className="glass-card">
            <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", color: "#9ca3af", marginBottom: "1rem" }}>
              <Users size={16} />
              <span>Nearby Peers ({peers.length})</span>
            </div>
            <div className="peer-list">
              {peers.map(p => (
                <div key={p} className="peer-item">
                  <div className="status-dot"></div>
                  <div style={{ overflow: "hidden", textOverflow: "ellipsis" }}>{p}</div>
                </div>
              ))}
              {peers.length === 0 && <div style={{ color: "#4b5563", fontSize: "0.8rem", textAlign: "center" }}>Scanning for peers...</div>}
            </div>
          </section>

          <section className="glass-card">
            <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", color: "#9ca3af", marginBottom: "1rem" }}>
              <Cpu size={16} />
              <span>System Health</span>
            </div>
            <div style={{ fontSize: "0.8rem", color: "#4b5563" }}>
              <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "0.5rem" }}>
                <span>CPU Usage</span>
                <span>2%</span>
              </div>
              <div style={{ backgroundColor: "#1f2937", height: "4px", borderRadius: "2px" }}>
                <div style={{ backgroundColor: "#818cf8", width: "15%", height: "100%", borderRadius: "2px" }}></div>
              </div>
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}

export default App;
