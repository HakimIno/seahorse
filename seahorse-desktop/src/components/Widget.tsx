import React, { forwardRef } from 'react';
import ReactECharts from 'echarts-for-react';
import { Icon } from '@iconify/react';

interface WidgetProps {
  id: string;
  title: string;
  option: any;
  onRemove: (id: string) => void;
  // RGL passes these props to its children
  style?: React.CSSProperties;
  className?: string;
  onMouseDown?: React.MouseEventHandler;
  onMouseUp?: React.MouseEventHandler;
  onTouchEnd?: React.TouchEventHandler;
}

const Widget = forwardRef<HTMLDivElement, WidgetProps>(({ 
  id, title, option, onRemove, style, className, onMouseDown, onMouseUp, onTouchEnd, ...props 
}, ref) => {
  return (
    <div 
      ref={ref}
      style={style}
      className={`${className} grid-item`}
      onMouseDown={onMouseDown}
      onMouseUp={onMouseUp}
      onTouchEnd={onTouchEnd}
      {...props}
    >
      <div className="widget-card">
        <div className="widget-header custom-drag-handle">
          <div className="widget-title">
            <span className="title-dot"></span>
            {title}
          </div>
          <div className="widget-actions">
            <button 
              onMouseDown={(e) => e.stopPropagation()} 
              onClick={() => onRemove(id)} 
              className="action-btn delete"
            >
              <Icon icon="lucide:trash-2" width="16" />
            </button>
          </div>
        </div>
        <div className="widget-content">
          <ReactECharts 
            option={option} 
            style={{ height: '100%', width: '100%' }}
            opts={{ renderer: 'canvas' }}
          />
        </div>
      </div>
    </div>
  );
});

export default Widget;
