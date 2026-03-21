import React, { useState } from 'react';
import { Responsive, WidthProvider } from '@eleung/react-grid-layout';
import Widget from './Widget';

import '@eleung/react-grid-layout/css/styles.css';
import '../styles/global.css';

const ResponsiveGridLayout = WidthProvider(Responsive);

interface WidgetData {
  id: string;
  title: string;
  type: string;
}

interface DashboardProps {
  initialWidgets?: WidgetData[];
}

const Dashboard: React.FC<DashboardProps> = ({ initialWidgets = [
  { id: '1', title: 'Revenue Trend', type: 'line' },
  { id: '2', title: 'Market Share', type: 'pie' },
  { id: '3', title: 'Sales by Store', type: 'bar' },
] }) => {
  const [items, setItems] = useState<WidgetData[]>(initialWidgets);
  const [layouts, setLayouts] = useState<any>({
    lg: [
      { i: '1', x: 0, y: 0, w: 2, h: 2 },
      { i: '2', x: 2, y: 0, w: 2, h: 2 },
      { i: '3', x: 0, y: 2, w: 4, h: 2 },
    ]
  });

  const onLayoutChange = (_: any, allLayouts: any) => {
    setLayouts(allLayouts);
    console.log('Layout changed:', allLayouts);
  };

  const removeWidget = (id: string) => {
    setItems(items.filter((item: WidgetData) => item.id !== id));
  };

  const mockOption = {
    tooltip: { trigger: 'axis' },
    xAxis: { type: 'category', data: ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'] },
    yAxis: { type: 'value' },
    series: [{ data: [150, 230, 224, 218, 135, 147, 260], type: 'line', smooth: true }]
  };

  return (
    <div className="dashboard-container">
      <div className="dashboard-header">
        <h2>Executive Business Dashboard</h2>
        <div className="dashboard-controls">
          <button className="add-btn">Add Analysis</button>
        </div>
      </div>

      <ResponsiveGridLayout
        className="layout"
        layouts={layouts}
        breakpoints={{ lg: 1200, md: 996, sm: 768, xs: 480, xxs: 0 }}
        cols={{ lg: 4, md: 4, sm: 2, xs: 1, xxs: 1 }}
        rowHeight={150}
        draggableHandle=".custom-drag-handle"
        onLayoutChange={onLayoutChange}
      >
        {items.map((item: WidgetData) => (
          <div key={item.id}>
            <Widget 
              id={item.id}
              title={item.title}
              onRemove={removeWidget}
              option={item.type === 'pie' ? {
                ...mockOption, series: [{ ...mockOption.series[0], type: 'pie', radius: '50%' }]
              } : mockOption}
            />
          </div>
        ))}
      </ResponsiveGridLayout>
    </div>
  );
};

export default Dashboard;
