import { createBrowserRouter } from 'react-router-dom';
import MainLayout from '../layouts/MainLayout';
import Analyst from '../pages/Analyst';
import Reports from '../pages/Reports';
import Memory from '../pages/Memory';
import Settings from '../pages/Settings';

export const router = createBrowserRouter([
    {
        path: '/',
        element: <MainLayout />,
        children: [
            {
                index: true,
                element: <Analyst />,
            },
            {
                path: 'reports',
                element: <Reports />,
            },
            {
                path: 'memory',
                element: <Memory />,
            },
            {
                path: 'settings',
                element: <Settings />,
            },
        ],
    },
]);
