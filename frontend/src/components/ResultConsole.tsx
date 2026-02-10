import React, { useMemo } from 'react';
import { FinalResult, UNIT_KEYS } from '../types';

interface ResultConsoleProps {
  finalResult: FinalResult | null;
}

export const ResultConsole: React.FC<ResultConsoleProps> = ({ finalResult }) => {
  const resultRows = useMemo(() => {
    if (!finalResult) return [];
    return UNIT_KEYS.map((unit) => {
      const vote = finalResult.votes[unit] || {};
      return {
        unit,
        vote: vote.vote ?? "N/A",
        reason: vote.reason ?? "",
      };
    });
  }, [finalResult]);

  return (
    <div className="panel result-console" id="result-console" style={{ display: finalResult ? "flex" : "none" }}>
      <div className="result-header">FINAL DECISION</div>
      <div className="result-content" id="result-content">
        {finalResult &&
          resultRows.map((row) => (
            <div className="vote-row" key={row.unit}>
              <span>{row.unit}:</span>
              <span className={row.vote === "YES" ? "vote-yes" : row.vote === "NO" ? "vote-no" : ""}>
                {row.vote}
              </span>
              {row.reason && <span className="vote-reason"> {row.reason}</span>}
            </div>
          ))}
        {finalResult?.summary && <div className="summary">{finalResult.summary}</div>}
      </div>
    </div>
  );
};
