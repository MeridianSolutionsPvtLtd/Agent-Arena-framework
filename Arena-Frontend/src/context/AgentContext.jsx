import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';
import { useAuth } from './AuthContext';
import { apiListAgents, apiGetAgentContext, apiDeleteAgent, apiGetSubAgentHistories, apiClearAgentHistory } from '../services/api';
import { DESKTOP_AGENT_ID, IS_DESKTOP_AGENT } from '../utils/desktopAgent';
import { normalizeMessageAttachments } from '../utils/attachmentUtils';

const AgentContext = createContext();

export const useAgent = () => useContext(AgentContext);

export const AgentProvider = ({ children }) => {
  const { isAuthenticated } = useAuth();
  const [agents, setAgents] = useState([]);
  const [loading, setLoading] = useState(false);

  // Local chat state for real-time UI updates (synced with backend on load)
  const [chats, setChats] = useState({});

  // Local activity state for the telemetry stream in the sidebar
  const [activities, setActivities] = useState({});

  const [subAgentHistories, setSubAgentHistories] = useState({});

  // ─── Fetch agents from backend ───────────────────────
  const fetchAgents = useCallback(async () => {
    if (!isAuthenticated) return;
    setLoading(true);
    try {
      const backendAgents = await apiListAgents();
      const scopedAgents = IS_DESKTOP_AGENT
        ? backendAgents.filter((a) => a.agent_id === DESKTOP_AGENT_ID)
        : backendAgents;

      // Filter out prebuilt agents generically so UI displays only custom/user-created agents
      const customAgents = scopedAgents.filter((a) => a.agent_kind !== 'prebuilt');

      // Map backend shape to UI shape
      const mapped = customAgents.map((a) => ({
        id: a.id || a._id || a.agent_id,
        agent_id: a.agent_id || a.id || a._id,
        name: a.name || 'Unnamed Agent',
        purpose: a.description || a.user_intent || a.purpose || '',
        capability: a.domain || a.capability || 'General',
        tone: 'Professional',
        status: 'Active',
        createdAt: a.created_at || new Date().toISOString(),
        interactions: 0,
        agent_kind: a.agent_kind || 'custom',
        // Store the full backend blueprint for reference
        _blueprint: a,
      }));
      setAgents(mapped);
    } catch (err) {
      console.error('Failed to fetch agents:', err);
    } finally {
      setLoading(false);
    }
  }, [isAuthenticated]);

  useEffect(() => {
    fetchAgents();
  }, [fetchAgents]);

  // ─── Load chat history from backend ──────────────────
  const loadChatHistory = useCallback(async (agentId) => {
    try {
      const data = await apiGetAgentContext(agentId);
      const totalTokens = data.total_tokens || 0;
      if (data.messages && data.messages.length > 0) {
        const mapped = data.messages.map((m, i) => {
          const isUser = m.sender === 'user';
          const { cleanText, attachments } = isUser
            ? normalizeMessageAttachments(m.text, m.attachments || m.metadata?.attachments)
            : { cleanText: m.text, attachments: m.attachments || m.metadata?.attachments || null };
          return {
            id: i + 1,
            sender: isUser ? 'user' : 'ai',
            text: cleanText,
            timestamp: new Date().toISOString(),
            trace_id: m.trace_id,
            collaboration: m.collaboration || null,
            artifacts: m.artifacts || null,
            attachments: attachments || null,
          };
        });
        setChats(prev => ({ ...prev, [agentId]: mapped }));
        return { threadId: data.thread_id, messages: mapped, totalTokens };
      }
      return { threadId: data.thread_id || null, messages: [], totalTokens };
    } catch (err) {
      console.error('Failed to load chat history:', err);
    }
    return { threadId: null, messages: [], totalTokens: 0 };
  }, []);

  const syncIntelligence = useCallback(async (agentId) => {
    try {
      const subHistories = await apiGetSubAgentHistories(agentId);
      setSubAgentHistories(prev => ({ ...prev, [agentId]: subHistories }));
      return { subAgentHistories: subHistories };
    } catch (err) {
      console.error('Failed to sync intelligence:', err);
    }
  }, []);

  // ─── Add agent to local state (called after backend create) ──
  const addAgent = (agent) => {
    const formattedAgent = {
      ...agent,
      agent_kind: agent.agent_kind || 'custom',
    };
    setAgents(prev => [formattedAgent, ...prev]);
    setChats(prev => ({
      ...prev,
      [agent.id]: [{
        id: Date.now(),
        sender: 'ai',
        text: `Hello! I am ${agent.name}. How can I assist you today?`,
        timestamp: new Date().toISOString()
      }]
    }));
    setActivities(prev => ({
      ...prev,
      [agent.id]: [{
        id: Date.now(),
        status: 'success',
        text: 'Agent initialized and ready',
        timestamp: new Date().toISOString()
      }]
    }));
  };

  const deleteAgent = async (id) => {
    try {
      await apiDeleteAgent(id);
      setAgents(prev => prev.filter(a => a.id !== id));
      setChats(prev => {
        const newChats = { ...prev };
        delete newChats[id];
        return newChats;
      });
      setActivities(prev => {
        const newAct = { ...prev };
        delete newAct[id];
        return newAct;
      });
    } catch (err) {
      console.error('Failed to delete agent:', err);
      alert('Failed to delete agent. Please try again.');
    }
  };

  const clearAgentHistory = async (id) => {
    try {
      await apiClearAgentHistory(id);
      const agentName = agents.find(a => a.id === id)?.name || 'your agent';
      setChats(prev => ({
        ...prev,
        [id]: [{
          id: Date.now(),
          sender: 'ai',
          text: `Context and history cleared successfully. Hello! I am ${agentName}. How can I assist you today?`,
          timestamp: new Date().toISOString()
        }]
      }));
      setActivities(prev => ({
        ...prev,
        [id]: [{
          id: Date.now(),
          status: 'success',
          text: 'Agent history and context cleared. Ready to start fresh.',
          timestamp: new Date().toISOString()
        }]
      }));
      setSubAgentHistories(prev => ({
        ...prev,
        [id]: {}
      }));
    } catch (err) {
      console.error('Failed to clear agent history:', err);
      alert('Failed to clear agent history. Please try again.');
    }
  };

  const addMessage = (agentId, message) => {
    let normalized = message;
    if (message?.sender === 'user' && typeof message.text === 'string' && message.text.includes('[Attachments]')) {
      const { cleanText, attachments } = normalizeMessageAttachments(message.text, message.attachments);
      normalized = { ...message, text: cleanText, attachments };
    }
    setChats(prev => ({
      ...prev,
      [agentId]: [...(prev[agentId] || []), normalized]
    }));
  };

  const addActivity = (agentId, activity) => {
    setActivities(prev => ({
      ...prev,
      [agentId]: [activity, ...(prev[agentId] || [])]
    }));
  };

  const clearActivities = useCallback((agentId) => {
    setActivities(prev => ({ ...prev, [agentId]: [] }));
  }, []);

  return (
    <AgentContext.Provider value={{
      agents,
      chats,
      activities,
      subAgentHistories,
      loading,
      addAgent,
      deleteAgent,
      clearAgentHistory,
      addMessage,
      addActivity,
      clearActivities,
      fetchAgents,
      loadChatHistory,
      syncIntelligence
    }}>
      {children}
    </AgentContext.Provider>
  );
};
