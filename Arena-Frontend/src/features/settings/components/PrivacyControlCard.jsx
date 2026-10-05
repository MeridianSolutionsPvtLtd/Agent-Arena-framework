import React from 'react';
import { Lock, CheckCircle2, AlertCircle } from 'lucide-react';
import { Input } from '../../../components/FormInputs';
import Button from '../../../components/Button';
import { useChangePassword } from '../hooks/useChangePassword';

// Password change, backed by POST /api/auth/change-password. Mirrors Arena's
// "Privacy Control" card (Current / New / Repeat + Update Access) in Playground's
// light theme, reusing the shared Input + Button primitives rather than bespoke
// inputs so it inherits focus rings, spacing and type scale from the design system.
export default function PrivacyControlCard() {
  const {
    current, setCurrent,
    next, setNext,
    repeat, setRepeat,
    status, message, hint, canSubmit, submit,
  } = useChangePassword();

  const onSubmit = (e) => {
    e.preventDefault();
    submit();
  };

  return (
    <form onSubmit={onSubmit} className="p-6 rounded-2xl bg-white border border-border">
      <div className="flex items-center gap-3 mb-1.5">
        <div className="w-10 h-10 rounded-xl bg-primary/10 flex items-center justify-center shrink-0">
          <Lock size={18} className="text-primary" />
        </div>
        <h3 className="text-lg font-bold text-text-primary">Privacy Control</h3>
      </div>
      <p className="text-sm text-text-secondary mb-5">
        Update the password used to sign in to your account.
      </p>

      <Input
        label="Current Password"
        id="settings-current-password"
        type="password"
        autoComplete="current-password"
        value={current}
        onChange={(e) => setCurrent(e.target.value)}
        placeholder="••••••••"
        className="mb-4"
      />

      <div className="grid sm:grid-cols-2 gap-4">
        <Input
          label="New Password"
          id="settings-new-password"
          type="password"
          autoComplete="new-password"
          value={next}
          onChange={(e) => setNext(e.target.value)}
          placeholder="••••••••"
        />
        <Input
          label="Repeat New"
          id="settings-repeat-password"
          type="password"
          autoComplete="new-password"
          value={repeat}
          onChange={(e) => setRepeat(e.target.value)}
          placeholder="••••••••"
        />
      </div>

      {/* Live validation hint (neutral) */}
      {hint && <p className="mt-3 text-xs font-medium text-text-secondary">{hint}</p>}

      {/* Result of the last submit */}
      {status === 'success' && (
        <p className="mt-3 flex items-center gap-2 text-xs font-bold text-green-700">
          <CheckCircle2 size={14} /> {message}
        </p>
      )}
      {status === 'error' && (
        <p className="mt-3 flex items-center gap-2 text-xs font-bold text-red-600">
          <AlertCircle size={14} /> {message}
        </p>
      )}

      <Button type="submit" disabled={!canSubmit} className="w-full mt-5">
        {status === 'saving' ? 'Updating…' : 'Update Access'}
      </Button>
    </form>
  );
}
