import { Message } from '../types/chat';
import ReactMarkdown from 'react-markdown';
import '../styles/MessageItem.css';

interface MessageItemProps {
    message: Message;
}

export default function MessageItem({ message }: MessageItemProps) {
    const isAI = message.role === 'ai';

    return (
        <div className={`message-item ${message.role}`}>
            {isAI && <div className="message-agent-name">AgentV2</div>}
            <div className="message-bubble">
                {message.contents.map((content, index) => (
                    <div key={index} className="content-item">
                        {content.type === 'image' && content.url && (
                            <div className="image-content">
                                <img src={content.url} alt={content.alt || (isAI ? 'Agent output' : 'User upload')} />
                            </div>
                        )}

                        {content.type === 'chart' && content.data && (
                            <div className="chart-preview-content">
                                <div className="chart-header">
                                    <span className="chart-title">{content.title || 'Data Analysis'}</span>
                                </div>
                                <div className="chart-placeholder">
                                    [Chart Visualization Data: {JSON.stringify(content.data)}]
                                </div>
                            </div>
                        )}

                        {content.type === 'text' && content.text && (
                            <div className="markdown-content">
                                <ReactMarkdown>{content.text}</ReactMarkdown>
                            </div>
                        )}
                    </div>
                ))}

                <div className="message-meta">
                    <span className="message-time">
                        {new Date(message.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                    </span>
                    {!isAI && <span className="message-status">✓✓</span>}
                </div>
            </div>
        </div>
    );
}
