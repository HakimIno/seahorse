import { Icon } from '@iconify/react';
import { NavLink } from 'react-router-dom';
import '../styles/Sidebar.css';

export default function Sidebar() {
    return (
        <aside className="sidebar">
            <div className="logo-section">
                <Icon icon="majesticons:waves-line" className="logo-icon" />
                <span className="logo-text">Seahorse</span>
            </div>

            <div className="search-container">
                <input
                    type="text"
                    className="sidebar-search"
                    placeholder="Search conversations..."
                />
            </div>

            <nav className="nav-links">
                <NavLink
                    to="/"
                    className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}
                >
                    <Icon icon="majesticons:chat-line" />
                    <span>Analyst</span>
                </NavLink>
                <NavLink
                    to="/reports"
                    className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}
                >
                    <Icon icon="majesticons:analytics-line" />
                    <span>Reports</span>
                </NavLink>
                <NavLink
                    to="/memory"
                    className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}
                >
                    <Icon icon="majesticons:brain-line" />
                    <span>Memory</span>
                </NavLink>
                <NavLink
                    to="/settings"
                    className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}
                >
                    <Icon icon="majesticons:settings-cog-line" />
                    <span>Settings</span>
                </NavLink>
            </nav>

            <div className="user-profile">
                <div className="avatar"></div>
                <div className="user-info">
                    <div className="user-name">Weerachit</div>
                    <div className="user-tier">Pro Account</div>
                </div>
            </div>
        </aside>
    );
}
