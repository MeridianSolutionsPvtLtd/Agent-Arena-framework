import React, { useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import {
  LayoutDashboard, Bot, PlusCircle, MessageSquare, Settings,
  User, ChevronLeft, LogOut, X, AlertTriangle, Blocks
} from 'lucide-react';
import { useAuth } from '../context/AuthContext';

const sidebarLinks = [
  { label: 'Overview', icon: LayoutDashboard, href: '/dashboard' },
  { label: 'My Agents', icon: Bot, href: '/catalog' },
  { label: 'Agent Builder', icon: PlusCircle, href: '/builder' },
  { label: 'Integrations', icon: Blocks, href: '/integrations' },
  { label: 'Chats', icon: MessageSquare, href: '/chats' },
];

export default function DashboardLayout({ children }) {
  const [collapsed, setCollapsed] = useState(false);
  const [showLogoutConfirm, setShowLogoutConfirm] = useState(false);
  const location = useLocation();
  const navigate = useNavigate();
  const { logout } = useAuth();
  // Matches the agent chat (/chat, /chat/:agentId) AND the persona chats
  // (/chats, /chats/:chatId) — both render full-screen with the app nav hidden.
  const isChatMode = location.pathname.startsWith('/chat');

  const handleConfirmLogout = () => {
    logout();
    navigate('/login');
  };

  if (isChatMode) {
    return <div className="h-screen w-screen overflow-hidden bg-white">{children}</div>;
  }

  return (
    <div className="flex h-screen bg-section-bg overflow-hidden">
      {/* ─── Sidebar ─────────────────────────────── */}
      <aside
        className={`
          flex flex-col bg-white border-r border-border transition-all duration-300 shrink-0
          ${collapsed ? 'w-[70px]' : 'w-[250px]'}
        `}
      >
        {/* Sidebar Header */}
        <div
          className={`h-16 flex items-center border-b border-border transition-all duration-300 relative ${
            collapsed ? 'justify-center px-2' : 'justify-between px-4'
          }`}
        >
          {!collapsed ? (
            <>
              <Link to="/" className="flex items-center">
                <img
                  src="/meridian-logo.png"
                  alt="Meridian AI"
                  className="h-8 w-auto object-contain"
                />
              </Link>
              <button
                onClick={() => setCollapsed(true)}
                className="p-1.5 rounded-lg text-text-secondary hover:bg-gray-100 transition-colors cursor-pointer"
                title="Collapse sidebar"
                aria-label="Collapse sidebar"
              >
                <ChevronLeft size={18} />
              </button>
            </>
          ) : (
            <>
              <Link
                to="/"
                className="w-10 h-10 flex items-center justify-center rounded-lg hover:bg-gray-50 transition-colors"
                title="Meridian AI"
              >
                <img
                  src="/favicon.png"
                  alt="Meridian AI"
                  className="h-8 w-8 object-contain"
                />
              </Link>
              <button
                onClick={() => setCollapsed(false)}
                className="absolute -right-3 top-1/2 -translate-y-1/2 w-6 h-6 bg-white border border-border rounded-full shadow-sm flex items-center justify-center text-text-secondary hover:text-text-primary hover:bg-gray-50 transition-all cursor-pointer z-20"
                title="Expand sidebar"
                aria-label="Expand sidebar"
              >
                <ChevronLeft size={14} className="rotate-180" />
              </button>
            </>
          )}
        </div>

        {/* Nav Links */}
        <nav className="flex-1 py-4 px-2 space-y-1 overflow-y-auto">
          {sidebarLinks.map((link) => {
            const active = location.pathname === link.href;
            return (
              <Link
                key={link.label}
                to={link.href}
                className={`
                  flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium
                  transition-colors duration-150
                  ${active
                    ? 'bg-light-blue text-primary'
                    : 'text-text-secondary hover:bg-gray-50 hover:text-text-primary'
                  }
                  ${collapsed ? 'justify-center' : ''}
                `}
                title={collapsed ? link.label : undefined}
              >
                <link.icon size={20} className="shrink-0" />
                {!collapsed && <span>{link.label}</span>}
              </Link>
            );
          })}
        </nav>

        {/* User section */}
        <div className="border-t border-border p-3">
          <div className={`flex items-center gap-3 ${collapsed ? 'justify-center' : ''}`}>
            <div className="w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center shrink-0">
              <User size={16} className="text-primary" />
            </div>
            {!collapsed && (
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-text-primary truncate">Admin User</p>
                <p className="text-xs text-text-secondary truncate">admin@meridian.com</p>
              </div>
            )}
          </div>
        </div>
      </aside>

      {/* ─── Main Content ────────────────────────── */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Topbar */}
        <header className="h-16 bg-white border-b border-border flex items-center justify-between px-6 shrink-0">
          <div className="flex items-center gap-3">
            {/* Search removed */}
          </div>

          <div className="flex items-center gap-4">
            {/* Notification removed */}
            <div className="w-px h-8 bg-border"></div>
            <div className="flex items-center gap-3">
              <div className="w-8 h-8 rounded-full bg-primary flex items-center justify-center">
                <span className="text-white text-xs font-semibold">AU</span>
              </div>
              <div className="hidden sm:block">
                <p className="text-sm font-medium text-text-primary">Admin User</p>
                <p className="text-xs text-text-secondary">Enterprise Plan</p>
              </div>
            </div>
            <div className="w-px h-8 bg-border hidden sm:block"></div>
            <button 
              onClick={() => setShowLogoutConfirm(true)}
              className="hidden sm:flex items-center gap-2 p-2 rounded-lg text-text-secondary hover:bg-red-50 hover:text-red-600 transition-colors cursor-pointer"
            >
              <LogOut size={18} />
            </button>
          </div>
        </header>

        {/* Page Content */}
        <main className="flex-1 overflow-y-auto p-6">
          {children}
        </main>
      </div>

      {/* ─── LOGOUT CONFIRMATION MODAL ─── */}
      {showLogoutConfirm && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm animate-in fade-in duration-300">
          <div className="bg-white rounded-[2.5rem] p-10 max-w-md w-full shadow-2xl border border-border/40 animate-in zoom-in-95 duration-300">
            <div className="w-16 h-16 bg-red-50 rounded-2xl flex items-center justify-center text-red-500 mx-auto mb-6 border border-red-100">
              <AlertTriangle size={32} />
            </div>
            <h2 className="text-2xl font-black text-text-primary text-center mb-3 tracking-tight">End Session?</h2>
            <p className="text-sm text-text-secondary text-center mb-8 font-medium leading-relaxed">
              Are you sure you want to log out? Your active agent neural links will be preserved, but you'll need to re-authenticate to access the arena.
            </p>
            <div className="flex gap-4">
              <button
                onClick={() => setShowLogoutConfirm(false)}
                className="flex-1 px-6 py-4 rounded-2xl bg-section-bg text-text-secondary font-black text-xs uppercase tracking-widest hover:bg-border/40 transition-colors"
              >
                Go Back
              </button>
              <button
                onClick={handleConfirmLogout}
                className="flex-1 px-6 py-4 rounded-2xl bg-red-500 text-white font-black text-xs uppercase tracking-widest hover:bg-red-600 shadow-lg shadow-red-500/20 transition-all active:scale-95"
              >
                Logout
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
