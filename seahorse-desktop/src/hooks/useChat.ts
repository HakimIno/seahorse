import { useState, useCallback } from 'react';
import { Message, ChatState } from '../types/chat';

export function useChat() {
    const [state, setState] = useState<ChatState>({
        messages: [
            {
                id: 'init',
                role: 'ai',
                contents: [{ type: 'text', text: 'สวัสดีครับ! ผม Seahorse AI พร้อมช่วยคุณวิเคราะห์ข้อมูลแล้วครับ' }],
                timestamp: Date.now()
            }
        ],
        isLoading: false,
        error: null,
    });

    const appendMessage = useCallback((message: Message) => {
        setState(prev => ({
            ...prev,
            messages: [...prev.messages, message],
        }));
    }, []);

    const sendMessage = useCallback(async (text: string) => {
        if (!text.trim()) return;

        const userMsg: Message = {
            id: Date.now().toString(),
            role: 'user',
            contents: [{ type: 'text', text }],
            timestamp: Date.now(),
        };

        appendMessage(userMsg);
        setState(prev => ({ ...prev, isLoading: true }));

        try {
            // Simulate backend delay
            setTimeout(() => {
                const responseContents: any[] = [
                    { type: 'text', text: `Backend received: "${text}". I am processing your request.` }
                ];

                // Combine content if specific keywords are found
                if (text.toLowerCase().includes('chart')) {
                    responseContents.push({
                        type: 'chart',
                        title: 'Sample Data Analysis',
                        data: { x: [1, 2, 3], y: [10, 20, 30] },
                        config: { type: 'line' }
                    });
                }

                if (text.toLowerCase().includes('markdown')) {
                    responseContents.push({
                        type: 'text',
                        text: `### Markdown Test\n- **Bold text**\n- *Italic text*\n- \`Inline code\`\n\n1. List item 1\n2. List item 2`
                    });
                }

                if (text.toLowerCase().includes('image') || text.toLowerCase().includes('png')) {
                    responseContents.push({
                        type: 'image',
                        url: 'https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/other/official-artwork/25.png',
                        alt: 'Sample PNG Image'
                    });
                }

                const aiMsg: Message = {
                    id: (Date.now() + 1).toString(),
                    role: 'ai',
                    contents: responseContents,
                    timestamp: Date.now(),
                };

                appendMessage(aiMsg);
                setState(prev => ({ ...prev, isLoading: false }));
            }, 1000);

        } catch (err) {
            setState(prev => ({
                ...prev,
                isLoading: false,
                error: 'Failed to connect to backend'
            }));
        }
    }, [appendMessage]);

    return {
        ...state,
        sendMessage,
    };
}
