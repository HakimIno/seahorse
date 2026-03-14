import { useState, useRef, useEffect } from "react";
import "./App.css";

interface Message {
  id: string;
  role: "user" | "ai";
  content: string;
}

function App() {
  const [messages, setMessages] = useState<Message[]>([
    { id: "1", role: "ai", content: "สวัสดีครับ! ผม Seahorse AI พร้อมช่วยคุณวิเคราะห์ข้อมูลบน MacBook แล้วครับ" }
  ]);
  const [input, setInput] = useState("");
  const [activeNav, setActiveNav] = useState("chat");
  const chatEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const handleSend = () => {
    if (!input.trim()) return;

    const userMsg: Message = { id: Date.now().toString(), role: "user", content: input };
    setMessages(prev => [...prev, userMsg]);
    setInput("");

    // Simulate AI thinking
    setTimeout(() => {
      const aiMsg: Message = {
        id: (Date.now() + 1).toString(),
        role: "ai",
        content: `คุณถามว่า: "${userMsg.content}"\nผมกำลังวิเคราะห์ข้อมูลให้กรุณารอสักครู่...`
      };
      setMessages(prev => [...prev, aiMsg]);
    }, 600);
  };

  return (
    <div className="app-container">
      {/* Sidebar */}
      <aside className="sidebar">
        <div className="logo-section">
          <span className="logo-icon">🌊</span>
          <span className="logo-text">Seahorse</span>
        </div>

        <div className="search-container">
          <input
            type="text"
            className="sidebar-search"
            placeholder="Search conversations..."
          />
        </div>

        <ul className="nav-links">
          <li
            className={`nav-item ${activeNav === 'chat' ? 'active' : ''}`}
            onClick={() => setActiveNav('chat')}
          >
            <span>💬</span> <span>Analyst</span>
          </li>
          <li
            className={`nav-item ${activeNav === 'reports' ? 'active' : ''}`}
            onClick={() => setActiveNav('reports')}
          >
            <span>📊</span> <span>Reports</span>
          </li>
          <li
            className={`nav-item ${activeNav === 'memory' ? 'active' : ''}`}
            onClick={() => setActiveNav('memory')}
          >
            <span>🧠</span> <span>Memory</span>
          </li>
          <li
            className={`nav-item ${activeNav === 'settings' ? 'active' : ''}`}
            onClick={() => setActiveNav('settings')}
          >
            <span>⚙️</span> <span>Settings</span>
          </li>
        </ul>

        <div className="user-profile">
          <div className="avatar"></div>
          <div style={{ flexGrow: 1 }}>
            <div style={{ fontSize: '0.9rem', fontWeight: 600 }}>Weerachit</div>
            <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Pro Account</div>
          </div>
        </div>
      </aside>

      {/* Main Content */}
      <main className="main-content">
        <header className="header">
          <div style={{ fontWeight: 600, fontSize: '1.25rem' }}>
            {activeNav === 'chat' ? 'Analyst' : activeNav.charAt(0).toUpperCase() + activeNav.slice(1)}
          </div>
          <div style={{ display: 'flex', gap: '16px', alignItems: 'center' }}>
            <span style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: '6px' }}>
              <span style={{ width: '8px', height: '8px', background: '#34a853', borderRadius: '50%' }}></span>
              Online
            </span>
          </div>
        </header>

        <div className="chat-container">
          {messages.map((m) => (
            <div key={m.id} className={`message ${m.role}`}>
              {m.content}
            </div>
          ))}
          <div ref={chatEndRef} />
        </div>

        <div className="input-area">
          <div className="input-wrapper">
            <input
              className="chat-input"
              placeholder="Ask Seahorse anything..."
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSend()}
            />
            <button className="send-btn" onClick={handleSend}>
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <line x1="22" y1="2" x2="11" y2="13"></line>
                <polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>
              </svg>
            </button>
          </div>
        </div>
      </main>
    </div>
  );
}

export default App;
