export type MessageRole = 'user' | 'ai';

export interface MessageContent {
    type: 'text' | 'image' | 'chart';
    text?: string;
    url?: string; // for images
    alt?: string;
    data?: any; // for charts
    config?: any;
    title?: string;
}

export interface Message {
    id: string;
    role: MessageRole;
    timestamp: number;
    contents: MessageContent[];
}

export interface ChatState {
    messages: Message[];
    isLoading: boolean;
    error: string | null;
}
