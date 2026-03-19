import { useEffect, useRef } from 'react';
import { Message } from '../types/chat';
import MessageItem from './MessageItem';
import '../styles/MessageList.css';

interface MessageListProps {
    messages: Message[];
}

export default function MessageList({ messages }: MessageListProps) {
    const listRef = useRef<HTMLDivElement>(null);

    useEffect(() => {
        if (listRef.current) {
            listRef.current.scrollTop = listRef.current.scrollHeight;
        }
    }, [messages]);

    return (
        <div className="message-list" ref={listRef}>
            {messages.map((msg) => (
                <MessageItem key={msg.id} message={msg} />
            ))}
        </div>
    );
}
