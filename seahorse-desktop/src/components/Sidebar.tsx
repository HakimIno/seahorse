import { Icon } from '@iconify/react';
import '../styles/Sidebar.css';

interface ChatItem {
    id: string;
    name: string;
    avatar: string;
    lastMessage: string;
    time: string;
    unread?: number;
    online?: boolean;
}

const mockChats: ChatItem[] = [
    {
        id: '1',
        name: 'AgentV3',
        avatar: 'https://api.dicebear.com/7.x/bottts/svg?seed=v3',
        lastMessage: 'ตารางสรุปยอดขายรายเดือน ปี 2025 อยู่ด้านบนครับ ไฮไลท์ที่น่าสนใจ...',
        time: '15:32',
        online: true,
    },
    {
        id: '2',
        name: 'AgentV2',
        avatar: 'https://api.dicebear.com/7.x/bottts/svg?seed=v2',
        lastMessage: 'นี่คือสรุปวิเคราะห์ยอดขายย้อนหลัง 3 เดือนครับ: ### สรุปก...',
        time: 'Thu',
        online: true,
    },
    {
        id: '3',
        name: 'seahorse',
        avatar: 'https://api.dicebear.com/7.x/bottts/svg?seed=sh',
        lastMessage: '📊 สรุป: ดึงข้อมูลยอดขายจากฐานข้อมูลมาวาดกราฟแล้วครับ ผลลัพ...',
        time: 'Wed',
    },
    {
        id: '4',
        name: 'Agent',
        avatar: 'https://api.dicebear.com/7.x/bottts/svg?seed=ag',
        lastMessage: '❌ ผมพบปัญหาขัดข้องชั่วคราว: litellm.APIError',
        time: 'Wed',
    },
];

export default function Sidebar() {
    return (
        <aside className="sidebar">
            <div className="sidebar-header">
                <button className="menu-btn">
                    <Icon icon="majesticons:menu-line" />
                </button>
                <div className="search-wrapper">
                    <input
                        type="text"
                        className="sidebar-search"
                        placeholder="Search"
                    />
                </div>
            </div>

            <div className="chat-list">
                {mockChats.map((chat) => (
                    <div key={chat.id} className={`chat-item ${chat.id === '2' ? 'active' : ''}`}>
                        <div className="chat-avatar-wrapper">
                            <img src={chat.avatar} alt={chat.name} className="chat-avatar" />
                            {chat.online && <span className="online-indicator"></span>}
                        </div>
                        <div className="chat-info">
                            <div className="chat-name-row">
                                <span className="chat-name">{chat.name}</span>
                                <span className="chat-time">{chat.time}</span>
                            </div>
                            <div className="chat-message-row">
                                <span className="chat-last-message">{chat.lastMessage}</span>
                                {chat.unread && <span className="unread-badge">{chat.unread}</span>}
                            </div>
                        </div>
                    </div>
                ))}
            </div>
        </aside>
    );
}
