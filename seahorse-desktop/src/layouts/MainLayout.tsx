import { Outlet } from 'react-router-dom';
import Sidebar from '../components/Sidebar';
import '../styles/MainLayout.css';

export default function MainLayout() {
    return (
        <div className="app-container">
            <Sidebar />
            <main className="main-content">
                <Outlet />
            </main>
        </div>
    );
}
