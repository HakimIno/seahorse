declare global {
    interface Document {
        startViewTransition(callback: () => void): {
            ready: Promise<void>;
            finished: Promise<void>;
            updateCallbackDone: Promise<void>;
        };
    }
}

import { useState, useEffect, useCallback } from 'react';

export function useTheme() {
    const [theme, setTheme] = useState<'light' | 'dark'>(() => {
        return (localStorage.getItem('theme') as 'light' | 'dark') || 'light';
    });

    useEffect(() => {
        if (theme === 'dark') {
            document.documentElement.classList.add('dark');
        } else {
            document.documentElement.classList.remove('dark');
        }
        localStorage.setItem('theme', theme);
    }, [theme]);

    const toggleTheme = useCallback((event: React.MouseEvent) => {
        const isDark = theme === 'dark';

        // Fallback for browsers that don't support View Transitions
        if (!document.startViewTransition) {
            setTheme(isDark ? 'light' : 'dark');
            return;
        }

        // Get the click position
        const x = event.clientX;
        const y = event.clientY;
        const endRadius = Math.hypot(
            Math.max(x, window.innerWidth - x),
            Math.max(y, window.innerHeight - y)
        );

        const transition = document.startViewTransition(() => {
            setTheme(isDark ? 'light' : 'dark');
        });

        transition.ready.then(() => {
            const clipPath = [
                `circle(0px at ${x}px ${y}px)`,
                `circle(${endRadius}px at ${x}px ${y}px)`,
            ];

            document.documentElement.animate(
                {
                    clipPath: isDark ? [...clipPath].reverse() : clipPath,
                },
                {
                    duration: 500,
                    easing: 'ease-in-out',
                    pseudoElement: isDark
                        ? '::view-transition-old(root)'
                        : '::view-transition-new(root)',
                }
            );
        });
    }, [theme]);

    return { theme, toggleTheme };
}
