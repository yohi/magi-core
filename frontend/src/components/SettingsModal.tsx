import React, { Dispatch, SetStateAction } from 'react';

export type UnitConfig = {
  name: string;
  model: string;
  temp: number;
  persona: string;
};

export type UnitSettingsMap = {
  melchior: UnitConfig;
  balthasar: UnitConfig;
  casper: UnitConfig;
};

interface SettingsModalProps {
  isOpen: boolean;
  currentEditingUnit: "melchior" | "balthasar" | "casper" | null;
  unitSettings: UnitSettingsMap;
  setUnitSettings: Dispatch<SetStateAction<UnitSettingsMap>>;
  saveSettings: () => void;
  closeModal: () => void;
}

export const SettingsModal: React.FC<SettingsModalProps> = ({
  isOpen,
  currentEditingUnit,
  unitSettings,
  setUnitSettings,
  saveSettings,
  closeModal,
}) => {
  if (!isOpen || !currentEditingUnit) return null;

  const currentSettings = unitSettings[currentEditingUnit];

  const handleModelChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    setUnitSettings((prev) => ({
      ...prev,
      [currentEditingUnit]: {
        ...prev[currentEditingUnit],
        model: event.target.value,
      },
    }));
  };

  const handleTempChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    setUnitSettings((prev) => ({
      ...prev,
      [currentEditingUnit]: {
        ...prev[currentEditingUnit],
        temp: Number(event.target.value),
      },
    }));
  };

  const handlePersonaChange = (event: React.ChangeEvent<HTMLTextAreaElement>) => {
    setUnitSettings((prev) => ({
      ...prev,
      [currentEditingUnit]: {
        ...prev[currentEditingUnit],
        persona: event.target.value,
      },
    }));
  };

  return (
    <div id="settings-modal" className="settings-modal" style={{ display: "flex" }}>
      <div className="modal-content">
        <h2 id="modal-title">UNIT: {currentSettings.name}</h2>
        <div className="form-group">
          <label>MODEL:</label>
          <input
            type="text"
            value={currentSettings.model}
            onChange={handleModelChange}
          />
        </div>
        <div className="form-group">
          <label>TEMPERATURE:</label>
          <input
            type="number"
            step="0.1"
            min={0}
            max={1}
            value={currentSettings.temp}
            onChange={handleTempChange}
          />
        </div>
        <div className="form-group">
          <label>PERSONA:</label>
          <textarea
            value={currentSettings.persona}
            onChange={handlePersonaChange}
          ></textarea>
        </div>
        <div className="modal-buttons">
          <button id="btn-save" onClick={saveSettings}>
            SAVE
          </button>
          <button id="btn-cancel-modal" onClick={closeModal}>
            CANCEL
          </button>
        </div>
      </div>
    </div>
  );
};
