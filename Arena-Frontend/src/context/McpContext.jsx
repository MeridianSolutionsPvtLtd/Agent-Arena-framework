import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';
import { useAuth } from './AuthContext';
import {
  apiGetMcpTemplates,
  apiGetMcpConnections,
  apiGetBuilderTools,
  apiCreateMcpConnection,
  apiDeleteMcpConnection,
  apiValidateMcpConnection,
  apiReconnectMcpConnection,
  apiSelectMcpTools,
} from '../services/api';

const McpContext = createContext();

export const useMcp = () => {
  const context = useContext(McpContext);
  if (!context) {
    throw new Error('useMcp must be used within an McpProvider');
  }
  return context;
};

export const McpProvider = ({ children }) => {
  const { isAuthenticated } = useAuth();

  const [templates, setTemplates] = useState([]);
  const [connections, setConnections] = useState([]);
  const [builderTools, setBuilderTools] = useState([]);
  const [builderToolsLoading, setBuilderToolsLoading] = useState(false);
  const [builderToolsError, setBuilderToolsError] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  // ─── Fetch Templates ─────────────────────────────────────────
  const fetchTemplates = useCallback(async () => {
    if (!isAuthenticated) return [];
    try {
      const data = await apiGetMcpTemplates();
      const list = Array.isArray(data) ? data : (data?.items || data?.templates || []);
      setTemplates(list);
      return list;
    } catch (err) {
      console.error('Failed to fetch MCP templates:', err);
      return [];
    }
  }, [isAuthenticated]);

  // ─── Fetch User Connections ──────────────────────────────────
  const fetchConnections = useCallback(async () => {
    if (!isAuthenticated) return [];
    try {
      const data = await apiGetMcpConnections();
      const list = Array.isArray(data) ? data : (data?.items || data?.connections || []);
      setConnections(list);
      return list;
    } catch (err) {
      console.error('Failed to fetch MCP connections:', err);
      return [];
    }
  }, [isAuthenticated]);

  // ─── Fetch Builder Tools ─────────────────────────────────────
  const fetchBuilderTools = useCallback(async () => {
    if (!isAuthenticated) return [];
    setBuilderToolsLoading(true);
    setBuilderToolsError(null);
    try {
      const data = await apiGetBuilderTools();
      const list = Array.isArray(data) ? data : (data?.items || data?.tools || []);
      setBuilderTools(list);
      setBuilderToolsError(null);
      return list;
    } catch (err) {
      console.error('Failed to fetch builder tools:', err);
      const errMsg = err?.message || 'Failed to fetch builder tools';
      setBuilderToolsError(errMsg);
      throw err;
    } finally {
      setBuilderToolsLoading(false);
    }
  }, [isAuthenticated]);

  // ─── Initial Load ────────────────────────────────────────────
  useEffect(() => {
    let isMounted = true;

    async function loadInitialData() {
      if (!isAuthenticated) {
        setTemplates([]);
        setConnections([]);
        setBuilderTools([]);
        setBuilderToolsError(null);
        setError(null);
        return;
      }

      setLoading(true);
      setError(null);

      try {
        await Promise.allSettled([
          fetchTemplates(),
          fetchConnections(),
          fetchBuilderTools(),
        ]);
      } catch (err) {
        if (isMounted) {
          setError(err?.message || 'Failed to initialize MCP services');
        }
      } finally {
        if (isMounted) {
          setLoading(false);
        }
      }
    }

    loadInitialData();

    return () => {
      isMounted = false;
    };
  }, [isAuthenticated, fetchTemplates, fetchConnections, fetchBuilderTools]);

  // ─── Mutation Operations ─────────────────────────────────────
  const createConnection = useCallback(async (payload) => {
    setError(null);
    const result = await apiCreateMcpConnection(payload);
    // Refresh connections and builder tools in background
    await Promise.allSettled([fetchConnections(), fetchBuilderTools()]);
    return result;
  }, [fetchConnections, fetchBuilderTools]);

  const deleteConnection = useCallback(async (capabilityId, version = '1.0.0') => {
    setError(null);
    await apiDeleteMcpConnection(capabilityId, version);
    // Optimistically remove from state & refresh
    setConnections(prev => prev.filter(c => !(c.capability_id === capabilityId && c.version === version)));
    await Promise.allSettled([fetchConnections(), fetchBuilderTools()]);
    return true;
  }, [fetchConnections, fetchBuilderTools]);

  const validateConnection = useCallback(async (capabilityId, version = '1.0.0') => {
    setError(null);
    const result = await apiValidateMcpConnection(capabilityId, version);
    await fetchConnections();
    return result;
  }, [fetchConnections]);

  const reconnectConnection = useCallback(async (capabilityId, version = '1.0.0', payload = {}) => {
    setError(null);
    const result = await apiReconnectMcpConnection(capabilityId, version, payload);
    await Promise.allSettled([fetchConnections(), fetchBuilderTools()]);
    return result;
  }, [fetchConnections, fetchBuilderTools]);

  const updateSelectedTools = useCallback(async (capabilityId, version = '1.0.0', toolNames = []) => {
    setError(null);
    const result = await apiSelectMcpTools(capabilityId, version, toolNames);
    await Promise.allSettled([fetchConnections(), fetchBuilderTools()]);
    return result;
  }, [fetchConnections, fetchBuilderTools]);

  const value = {
    templates,
    connections,
    builderTools,
    builderToolsLoading,
    builderToolsError,
    loading,
    error,
    fetchTemplates,
    fetchConnections,
    fetchBuilderTools,
    createConnection,
    deleteConnection,
    validateConnection,
    reconnectConnection,
    updateSelectedTools,
  };

  return (
    <McpContext.Provider value={value}>
      {children}
    </McpContext.Provider>
  );
};
