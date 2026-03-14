import { useState } from 'react';
import { Icon } from '@iconify/react';
import { NavLink } from 'react-router-dom';
import { useTheme } from '../hooks/useTheme';
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
    const [isMenuOpen, setIsMenuOpen] = useState(false);
    const { theme, toggleTheme } = useTheme();

    return (
        <aside className="sidebar">
            {/* Drawer Overlay */}
            {isMenuOpen && <div className="drawer-overlay" onClick={() => setIsMenuOpen(false)}></div>}

            {/* Side Drawer */}
            <div className={`side-drawer ${isMenuOpen ? 'open' : ''}`}>
                <div className="drawer-header">
                    <div className="drawer-user-info">
                        <div className="drawer-avatar"></div>
                        <div className="drawer-user-details">
                            <div className="drawer-user-name">Weerachit</div>
                            <div className="drawer-user-phone">+66 XX XXX XXXX</div>
                        </div>
                    </div>
                    <button className="drawer-theme-toggle" onClick={(e) => toggleTheme(e)}>
                        <Icon icon={theme === 'dark' ? "majesticons:sun-line" : "majesticons:moon-line"} />
                    </button>
                </div>

                <nav className="drawer-nav">
                    <NavLink to="/profile" className="drawer-item" onClick={() => setIsMenuOpen(false)}>
                        <Icon icon="majesticons:user-line" />
                        <span>My Profile</span>
                    </NavLink>
                    <NavLink to="/reports" className="drawer-item" onClick={() => setIsMenuOpen(false)}>
                        <Icon icon="majesticons:analytics-line" />
                        <span>Reports</span>
                    </NavLink>
                    <NavLink to="/memory" className="drawer-item" onClick={() => setIsMenuOpen(false)}>
                        <Icon icon="majesticons:brain-line" />
                        <span>Memory</span>
                    </NavLink>
                    <NavLink to="/settings" className="drawer-item" onClick={() => setIsMenuOpen(false)}>
                        <Icon icon="majesticons:settings-cog-line" />
                        <span>Settings</span>
                    </NavLink>
                    <div className="drawer-divider"></div>
                    <div className="drawer-item">
                        <Icon icon="majesticons:logout-line" />
                        <span>Logout</span>
                    </div>
                </nav>
            </div>

            <div className="sidebar-header">
                <button className="menu-btn" onClick={() => setIsMenuOpen(true)}>
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
