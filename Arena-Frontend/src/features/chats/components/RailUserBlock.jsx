import React, { useState } from 'react';
import { Settings } from 'lucide-react';
import { useAuth } from '../../../context/AuthContext';
import SettingsModal from '../../settings/SettingsModal';
import { initialFor } from '../../settings/components/ProfileHeader';

// Pinned to the bottom of the conversation rail: the signed-in identity, which
// opens the Settings dialog (profile / Log Out / Privacy Control). Same position
// Arena used, restyled for Playground's light rail.
export default function RailUserBlock() {
  const { user } = useAuth();
  const [open, setOpen] = useState(false);

  return (
    <>
      <div className="shrink-0 border-t border-border p-3">
        <button
          onClick={() => setOpen(true)}
          className="w-full group flex items-center gap-3 px-2 py-2 rounded-xl hover:bg-gray-50 transition-colors cursor-pointer text-left"
          title="Settings"
        >
          <div className="w-9 h-9 rounded-xl bg-primary flex items-center justify-center shrink-0">
            <span className="text-white text-sm font-black">{initialFor(user)}</span>
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-sm font-bold text-text-primary truncate">{user?.name || 'Account'}</p>
            <p className="text-xs text-text-secondary truncate">{user?.email || 'Signed in'}</p>
          </div>
          <Settings
            size={16}
            className="shrink-0 text-text-secondary/60 group-hover:text-primary transition-colors"
          />
        </button>
      </div>

      <SettingsModal open={open} onClose={() => setOpen(false)} />
    </>
  );
}
