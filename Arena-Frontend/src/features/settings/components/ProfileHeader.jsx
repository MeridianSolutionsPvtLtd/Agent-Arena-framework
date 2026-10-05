import React from 'react';
import { Mail, LogOut } from 'lucide-react';

/** Initial used for the avatar tile — falls back through name → email → '?'. */
export function initialFor(user) {
  const source = (user?.name || user?.email || '').trim();
  return source ? source[0].toUpperCase() : '?';
}

// Identity row: avatar, display name, email, and Log Out. Adapted from Arena's
// settings header into Playground's light theme (Arena used a violet gradient
// tile + red pill on near-black; here it's the primary blue tile on white).
export default function ProfileHeader({ user, onLogout }) {
  const name = user?.name || 'Signed in';
  const email = user?.email || '';

  return (
    <div className="flex items-center gap-4 p-5 rounded-2xl bg-white border border-border">
      <div className="w-12 h-12 rounded-xl bg-primary flex items-center justify-center shrink-0">
        <span className="text-white text-lg font-black">{initialFor(user)}</span>
      </div>

      <div className="flex-1 min-w-0">
        <p className="text-base font-bold text-text-primary truncate">{name}</p>
        {email && (
          <p className="flex items-center gap-1.5 text-sm text-text-secondary truncate">
            <Mail size={14} className="shrink-0" />
            <span className="truncate">{email}</span>
          </p>
        )}
      </div>

      <button
        onClick={onLogout}
        className="shrink-0 inline-flex items-center gap-2 px-4 py-2.5 rounded-lg bg-red-600 text-white text-sm font-semibold hover:bg-red-700 transition-colors active:scale-95 cursor-pointer"
      >
        <LogOut size={16} /> Log Out
      </button>
    </div>
  );
}
