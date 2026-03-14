import { useState, useRef, useEffect } from "react";
import { Icon } from '@iconify/react';
import '../styles/Analyst.css';

interface Message {
    id: string;
    role: "user" | "ai";
    content: string;
}

export default function Analyst() {
    const [messages, setMessages] = useState<Message[]>([
        { id: "1", role: "ai", content: "สวัสดีครับ! ผม Seahorse AI พร้อมช่วยคุณวิเคราะห์ข้อมูลบน MacBook แล้วครับ" }
    ]);
    const [input, setInput] = useState("");
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
        <>
            <header className="header">
                <div className="header-title">Analyst</div>
                <div className="header-status">
                    <span className="status-dot"></span>
                    Online
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
                        <Icon icon="majesticons:send-line" />
                    </button>
                </div>
            </div>
        </>
    );
}
