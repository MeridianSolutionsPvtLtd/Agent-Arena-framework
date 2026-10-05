import React, { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { X, Settings as SettingsIcon } from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import ProfileHeader from './components/ProfileHeader';
import PrivacyControlCard from './components/PrivacyControlCard';

// Settings dialog opened from the chat rail's user block. Composes the account
// cards; each card owns its own data/actions so this shell stays presentational
// and the same cards can be dropped onto a future /settings route unchanged.
//
// NOTE: Arena's settings also shows a Storage Usage meter. That is deliberately
// NOT here — deferred to Slice 2 (see the feature backlog). The data it needs is
// already available (GET /api/auth/me returns storage_used_bytes /
// storage_limit_bytes; GET /api/auth/usage and POST /api/auth/sync-storage also
// exist), so adding it later requires no backend work.
export default function SettingsModal({ open, onClose }) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  // Escape closes; lock background scroll while open.
  useEffect(() => {
    if (!open) return;
    const onKeyDown = (e) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKeyDown);
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.removeEventListener('keydown', onKeyDown);
      document.body.style.overflow = previousOverflow;
    };
  }, [open, onClose]);

  if (!open) return null;

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm animate-in fade-in duration-200"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label="Account settings"
    >
      <div
        className="w-full max-w-2xl max-h-[90vh] overflow-y-auto custom-scrollbar bg-section-bg rounded-3xl border border-border shadow-2xl animate-in zoom-in-95 duration-200"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="sticky top-0 z-10 flex items-center justify-between px-6 py-4 bg-white border-b border-border rounded-t-3xl">
          <div className="flex items-center gap-2.5">
            <SettingsIcon size={18} className="text-primary" />
            <h2 className="text-base font-bold text-text-primary">Settings</h2>
          </div>
          <button
            onClick={onClose}
            className="p-2 rounded-lg text-text-secondary hover:bg-gray-100 hover:text-text-primary transition-colors cursor-pointer"
            aria-label="Close settings"
          >
            <X size={18} />
          </button>
        </div>

        {/* Body */}
        <div className="p-6 space-y-5">
          <ProfileHeader user={user} onLogout={handleLogout} />
          <PrivacyControlCard />
        </div>
      </div>
    </div>
  );
}
