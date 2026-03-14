import { useState } from "react";
import { Icon } from '@iconify/react';
import { useChat } from '../hooks/useChat';
import MessageList from '../components/MessageList';
import '../styles/Analyst.css';

export default function Analyst() {
    const { messages, isLoading, sendMessage, error } = useChat();
    const [input, setInput] = useState("");

    const handleSend = () => {
        if (!input.trim() || isLoading) return;
        sendMessage(input);
        setInput("");
    };

    return (
        <div className="analyst-page">
            <header className="header">
                <div className="header-left">
                    <div className="header-title">AgentV2</div>
                    <div className="header-status">
                        {isLoading ? 'Processing...' : '2 subscribers'}
                    </div>
                </div>
                <div className="header-actions">
                    <Icon icon="majesticons:search-line" className="icon-btn" />
                    <Icon icon="majesticons:more-vertical-line" className="icon-btn" />
                    <Icon icon="majesticons:layout-line" className="icon-btn" />
                </div>
            </header>

            <MessageList messages={messages} />

            {error && <div className="error-banner">{error}</div>}

            <div className="input-area">
                <div className="input-wrapper">
                    <Icon icon="majesticons:paperclip-line" style={{ color: '#707579', fontSize: '1.4rem' }} />
                    <input
                        className="chat-input"
                        placeholder="Broadcast a message..."
                        value={input}
                        onChange={(e) => setInput(e.target.value)}
                        onKeyDown={(e) => e.key === 'Enter' && handleSend()}
                        disabled={isLoading}
                    />
                    <div className="input-actions" style={{ display: 'flex', gap: '12px', alignItems: 'center' }}>
                        <Icon icon="majesticons:emoji-line" style={{ color: '#707579', fontSize: '1.4rem' }} />
                        <button
                            className={`send-btn ${isLoading ? 'disabled' : ''}`}
                            onClick={handleSend}
                            disabled={isLoading}
                        >
                            <Icon icon={isLoading ? "majesticons:loading-line" : "majesticons:send-line"} className={isLoading ? "spin" : ""} />
                        </button>
                    </div>
                </div>
            </div>
        </div>
    );
}
