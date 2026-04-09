import React, { Dispatch, SetStateAction, useState, useEffect } from 'react';
import { AllUnitSettings, SystemSettings, ModelDefinition } from '../types';

interface SettingsModalProps {
  isOpen: boolean;
  currentEditingUnit: "melchior" | "balthasar" | "casper" | "system" | null;
  unitSettings: AllUnitSettings;
  setUnitSettings: Dispatch<SetStateAction<AllUnitSettings>>;
  systemSettings: SystemSettings;
  setSystemSettings: Dispatch<SetStateAction<SystemSettings>>;
  modelDefinitions: ModelDefinition[];
  saveSettings: () => void;
  closeModal: () => void;
}

const SUPPORTED_PROVIDERS = [
  { id: "anthropic", name: "Anthropic (Claude)" },
  { id: "openai", name: "OpenAI (GPT-4o/o1)" },
  { id: "google", name: "Google (Gemini)" },
  { id: "groq", name: "Groq (Llama-3)" },
  { id: "openrouter", name: "OpenRouter" },
  { id: "flixa", name: "Flixa" },
  { id: "mistral", name: "Mistral AI" },
  { id: "deepseek", name: "DeepSeek" },
  { id: "local", name: "Local LLM (Ollama/vLLM)" }
];

export const SettingsModal: React.FC<SettingsModalProps> = ({
  isOpen,
  currentEditingUnit,
  unitSettings,
  setUnitSettings,
  systemSettings,
  setSystemSettings,
  modelDefinitions,
  saveSettings,
  closeModal,
}) => {
  const [newProviderId, setNewProviderId] = useState("openai");
  const [newProviderKey, setNewProviderKey] = useState("");
  const [modelSearch, setModelSearch] = useState("");

  if (!isOpen || !currentEditingUnit) return null;

  const isSystem = currentEditingUnit === "system";
  const unitKey = isSystem ? null : currentEditingUnit;
  const currentUnit = unitKey ? unitSettings[unitKey] : null;

  // Handlers for Unit Settings
  const handleUnitChange = (field: string, value: any) => {
    if (!unitKey) return;
    setUnitSettings(prev => ({
      ...prev,
      [unitKey]: { ...prev[unitKey], [field]: value }
    }));
  };

  // Handlers for System Settings
  const handleSystemChange = (field: string, value: any) => {
    setSystemSettings(prev => ({ ...prev, [field]: value }));
  };

  const addProvider = () => {
    if (!newProviderKey) return;
    setSystemSettings(prev => ({
      ...prev,
      providers: { ...prev.providers, [newProviderId]: newProviderKey }
    }));
    setNewProviderKey("");
  };

  const removeProvider = (id: string) => {
    setSystemSettings(prev => {
      const next = { ...prev.providers };
      delete next[id];
      const nextOptions = { ...prev.providerOptions };
      delete nextOptions[id];
      return { ...prev, providers: next, providerOptions: nextOptions };
    });
  };

  const toggleProviderOption = (providerId: string, optionKey: string) => {
    setSystemSettings(prev => {
      const providerOptions = prev.providerOptions || {};
      const currentOptions = providerOptions[providerId] || {};
      const newValue = !currentOptions[optionKey];
      
      return {
        ...prev,
        providerOptions: {
          ...providerOptions,
          [providerId]: {
            ...currentOptions,
            [optionKey]: newValue
          }
        }
      };
    });
  };

  const filteredProviders = SUPPORTED_PROVIDERS.filter(p => systemSettings.whitelistProviders.includes(p.id));
  const activeProviderIds = Object.keys(systemSettings.providers);
  const providerModels = currentUnit ? modelDefinitions.filter(m => m.provider === currentUnit.provider) : [];
  const availableModels = providerModels.filter(m => 
    m.name.toLowerCase().includes(modelSearch.toLowerCase()) || 
    m.id.toLowerCase().includes(modelSearch.toLowerCase())
  );

  const handleProviderChange = (newProvider: string) => {
    if (!unitKey) return;
    setModelSearch("");
    // プロバイダが変更されたら、そのプロバイダの最初のモデルをデフォルトとしてセットする
    const firstModel = modelDefinitions.find(m => m.provider === newProvider);
    setUnitSettings(prev => ({
      ...prev,
      [unitKey]: { 
        ...prev[unitKey], 
        provider: newProvider,
        model: firstModel ? firstModel.id : prev[unitKey].model
      }
    }));
  };

  return (
    <div id="settings-modal" className="settings-modal" style={{ display: "flex" }}>
      <div className="modal-content" style={{ width: '550px', maxHeight: '90vh', overflowY: 'auto' }}>
        <h2 id="modal-title">{isSystem ? "SYSTEM SETTINGS" : `UNIT: ${currentUnit?.name}`}</h2>
        
        {isSystem ? (
          /* System Settings UI */
          <div id="system-fields">
            <div style={{ border: '1px dashed #444', padding: '15px', marginBottom: '15px' }}>
              <div style={{ fontSize: '12px', color: 'var(--magi-blue)', marginBottom: '12px' }}>Provider Management</div>
              <div className="form-group">
                <label>PROVIDER TYPE:</label>
                <select 
                  value={newProviderId} 
                  onChange={(e) => setNewProviderId(e.target.value)}
                  style={{ width: '100%', background: '#111', color: 'var(--magi-orange)', border: '1px solid var(--magi-orange)', padding: '8px' }}
                >
                  {filteredProviders.map(p => (
                    <option key={p.id} value={p.id}>{p.name}</option>
                  ))}
                </select>
              </div>
              <div className="form-group">
                <label>API KEY:</label>
                <input 
                  type="password" 
                  value={newProviderKey}
                  onChange={(e) => setNewProviderKey(e.target.value)}
                  placeholder="ENTER API KEY FOR THIS PROVIDER" 
                  style={{ width: '100%' }}
                />
              </div>
              <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: '10px' }}>
                <button onClick={addProvider} style={{ width: '150px', fontSize: '14px', padding: '6px' }} type="button">
                  REGISTER / UPDATE
                </button>
              </div>
              <div style={{ fontSize: '11px', marginTop: '15px', borderTop: '1px solid #333', paddingTop: '10px', color: '#aaa' }}>
                <div style={{ color: '#666', marginBottom: '5px' }}>ACTIVE PROVIDERS:</div>
                {activeProviderIds.map(id => (
                  <div key={id} style={{ marginBottom: '8px', borderBottom: '1px solid #222', paddingBottom: '4px' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <span>{id.toUpperCase()}: ********</span>
                      <a href="#" onClick={(e) => { e.preventDefault(); removeProvider(id); }} style={{ color: 'var(--magi-red)', textDecoration: 'none' }}>[DEL]</a>
                    </div>
                    {/* OpenAI互換または特定プロバイダ向けの追加オプション */}
                    {["openai", "flixa", "openrouter", "google", "groq", "local"].includes(id) && (
                      <div style={{ display: 'flex', alignItems: 'center', marginTop: '4px', color: '#888' }}>
                        <input 
                          type="checkbox" 
                          id={`verify-ssl-${id}`}
                          checked={!(systemSettings.providerOptions?.[id]?.verify_ssl === false)}
                          onChange={() => toggleProviderOption(id, "verify_ssl")}
                          style={{ width: 'auto', marginRight: '6px' }}
                        />
                        <label htmlFor={`verify-ssl-${id}`} style={{ cursor: 'pointer', fontSize: '10px' }}>
                          ENABLE SSL VERIFICATION
                        </label>
                      </div>
                    )}
                  </div>
                ))}
                {activeProviderIds.length === 0 && <div>No providers configured.</div>}
              </div>
            </div>

            <div style={{ border: '1px dashed #444', padding: '15px', marginBottom: '15px' }}>
              <div style={{ fontSize: '12px', color: 'var(--magi-blue)', marginBottom: '12px' }}>Consensus Protocol</div>
              <div className="form-group">
                <label>DEBATE ROUNDS:</label>
                <input 
                  type="number" 
                  min={1} 
                  max={5} 
                  value={systemSettings.debateRounds}
                  onChange={(e) => handleSystemChange('debateRounds', parseInt(e.target.value))}
                />
              </div>
              <div className="form-group">
                <label>VOTING THRESHOLD:</label>
                <select 
                  value={systemSettings.votingThreshold}
                  onChange={(e) => handleSystemChange('votingThreshold', e.target.value)}
                  style={{ width: '100%', background: '#111', color: 'var(--magi-orange)', border: '1px solid var(--magi-orange)', padding: '8px' }}
                >
                  <option value="majority">MAJORITY (多数決)</option>
                  <option value="unanimous">UNANIMOUS (満場一致)</option>
                </select>
              </div>
            </div>
          </div>
        ) : (
          /* Unit Settings UI */
          <div id="unit-fields">
            <div className="form-group">
              <label>PROVIDER:</label>
              <select 
                value={currentUnit?.provider} 
                onChange={(e) => handleProviderChange(e.target.value)}
                style={{ width: '100%', background: '#111', color: 'var(--magi-orange)', border: '1px solid var(--magi-orange)', padding: '8px' }}
              >
                {filteredProviders.map(p => (
                  <option key={p.id} value={p.id}>{p.name.toUpperCase()}</option>
                ))}
                {filteredProviders.length === 0 && <option value="">NO PROVIDERS IN WHITELIST</option>}
              </select>
              {currentUnit && !activeProviderIds.includes(currentUnit.provider) && !currentUnit.apiKey && (
                <div style={{ color: 'var(--magi-red)', fontSize: '11px', marginTop: '4px' }}>
                  ⚠ API KEY NOT CONFIGURED IN SYSTEM. PLEASE PROVIDE AN OVERRIDE KEY BELOW.
                </div>
              )}
            </div>
            <div className="form-group">
              <label>MODEL:</label>
              <input
                type="text"
                placeholder="SEARCH MODELS..."
                value={modelSearch}
                onChange={(e) => setModelSearch(e.target.value)}
                style={{ 
                  width: '100%', 
                  background: '#111', 
                  color: 'var(--magi-orange)', 
                  border: '1px solid var(--magi-orange)', 
                  padding: '5px',
                  marginBottom: '5px',
                  fontSize: '12px'
                }}
              />
              <select 
                value={currentUnit?.model} 
                onChange={(e) => handleUnitChange('model', e.target.value)}
                style={{ width: '100%', background: '#111', color: 'var(--magi-orange)', border: '1px solid var(--magi-orange)', padding: '8px' }}
                size={availableModels.length > 1 ? Math.min(availableModels.length, 5) : 1}
              >
                {availableModels.map(m => (
                  <option key={m.id} value={m.id}>{m.name}</option>
                ))}
                {availableModels.length === 0 && <option value="">NO MODELS MATCH SEARCH</option>}
              </select>
            </div>
            <div className="form-group">
              <label>TEMPERATURE:</label>
              <input
                type="number"
                step="0.1"
                min={0}
                max={1}
                value={currentUnit?.temp}
                onChange={(e) => handleUnitChange('temp', parseFloat(e.target.value))}
              />
            </div>
            <div className="form-group">
              <label>API KEY OVERRIDE (Optional):</label>
              <input
                type="password"
                value={currentUnit?.apiKey || ""}
                onChange={(e) => handleUnitChange('apiKey', e.target.value)}
                placeholder="LEAVE BLANK TO USE PROVIDER KEY"
              />
            </div>
            <div className="form-group">
              <label>PERSONA:</label>
              <textarea
                value={currentUnit?.persona}
                onChange={(e) => handleUnitChange('persona', e.target.value)}
                style={{ height: '120px' }}
              ></textarea>
            </div>
          </div>
        )}

        <div className="modal-buttons">
          <button id="btn-save" onClick={saveSettings} type="button">
            SAVE
          </button>
          <button id="btn-cancel-modal" onClick={closeModal} type="button">
            CANCEL
          </button>
        </div>
      </div>
    </div>
  );
};
