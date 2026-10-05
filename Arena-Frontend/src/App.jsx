import React from 'react';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import MainLayout from './layouts/MainLayout';
import DashboardLayout from './layouts/DashboardLayout';
import LandingPage from './pages/LandingPage';
import AgentCatalog from './pages/AgentCatalog';
import Dashboard from './pages/Dashboard';
import AgentBuilder from './pages/AgentBuilder';
import Integrations from './pages/Integrations';
import Chat from './pages/Chat';
import Login from './pages/Login';
import ChatsPage from './features/chats/ChatsPage';
import { ChatsProvider } from './features/chats/context/ChatsProvider';
import { DESKTOP_AGENT_ID, IS_DESKTOP_AGENT } from './utils/desktopAgent';

import { AgentProvider } from './context/AgentContext';
import { AuthProvider } from './context/AuthContext';
import { McpProvider } from './context/McpContext';

export default function App() {
  const homeElement = IS_DESKTOP_AGENT
    ? <Login />
    : <MainLayout><LandingPage /></MainLayout>;
  const chatElement = <DashboardLayout><Chat /></DashboardLayout>;
  const chatsElement = (
    <DashboardLayout>
      <ChatsProvider>
        <ChatsPage />
      </ChatsProvider>
    </DashboardLayout>
  );

  return (
    <AuthProvider>
      <AgentProvider>
        <McpProvider>
          <BrowserRouter>
            <Routes>
              <Route path="/login" element={<Login />} />
              <Route path="/signup" element={<Login initialSignup={true} />} />
              
              {/* Public pages with MainLayout */}
              <Route path="/" element={homeElement} />

              {/* Dashboard pages with DashboardLayout */}
              <Route path="/catalog" element={<DashboardLayout><AgentCatalog /></DashboardLayout>} />
              <Route path="/dashboard" element={<DashboardLayout><Dashboard /></DashboardLayout>} />
              <Route path="/builder" element={<DashboardLayout><AgentBuilder /></DashboardLayout>} />
              <Route path="/integrations" element={<DashboardLayout><Integrations /></DashboardLayout>} />
              <Route path="/chat" element={chatElement} />
              <Route path="/chat/:agentId" element={chatElement} />
              <Route path="/chats" element={chatsElement} />
              <Route path="/chats/:chatId" element={chatsElement} />
              {IS_DESKTOP_AGENT && <Route path="/desktop" element={<DashboardLayout><Chat forcedAgentId={DESKTOP_AGENT_ID} /></DashboardLayout>} />}
            </Routes>
          </BrowserRouter>
        </McpProvider>
      </AgentProvider>
    </AuthProvider>
  );
}
