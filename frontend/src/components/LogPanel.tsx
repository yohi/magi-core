import React, { forwardRef } from 'react';
import { LogEntry } from '../types';

interface LogPanelProps {
  logs: LogEntry[];
}

export const LogPanel = forwardRef<HTMLDivElement, LogPanelProps>(({ logs }, ref) => {
  return (
    <div className="panel log-panel" id="log-container" ref={ref}>
      {logs.map((log) => (
        <div key={log.id} className={`log-entry ${log.level}`}>
          {log.message}
        </div>
      ))}
    </div>
  );
});

LogPanel.displayName = 'LogPanel';
