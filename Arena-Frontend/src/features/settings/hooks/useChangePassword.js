import { useState, useCallback } from 'react';
import { apiChangePassword } from '../../../services/auth.api';

// Form state + submit for the Privacy Control card. Validation is client-side
// first (cheap, immediate) and the backend is the final authority on whether the
// current password is right — POST /api/auth/change-password answers 400
// "Current password is incorrect", which we surface verbatim.
//
// Security: passwords live only in this component's state for the duration of the
// request and are cleared on success. Nothing is logged or persisted anywhere.
export const MIN_PASSWORD_LENGTH = 8;

export function useChangePassword() {
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [repeat, setRepeat] = useState('');
  const [status, setStatus] = useState('idle'); // idle | saving | success | error
  const [message, setMessage] = useState('');

  const reset = useCallback(() => {
    setCurrent('');
    setNext('');
    setRepeat('');
    setStatus('idle');
    setMessage('');
  }, []);

  // Local rules; the submit button stays disabled until all of these pass.
  const canSubmit =
    current.length > 0 &&
    next.length >= MIN_PASSWORD_LENGTH &&
    next === repeat &&
    next !== current &&
    status !== 'saving';

  // Inline hint shown under the fields as the user types (not an error state).
  let hint = '';
  if (next && next.length < MIN_PASSWORD_LENGTH) hint = `Use at least ${MIN_PASSWORD_LENGTH} characters.`;
  else if (next && repeat && next !== repeat) hint = 'The new passwords do not match.';
  else if (next && current && next === current) hint = 'The new password must differ from the current one.';

  const submit = useCallback(async () => {
    if (!canSubmit) return false;
    setStatus('saving');
    setMessage('');
    try {
      await apiChangePassword(current, next);
      // Clear the fields so the secrets don't linger in state / the DOM.
      setCurrent('');
      setNext('');
      setRepeat('');
      setStatus('success');
      setMessage('Password updated.');
      return true;
    } catch (e) {
      setStatus('error');
      setMessage(e.message || 'Could not update the password.');
      return false;
    }
  }, [canSubmit, current, next]);

  return {
    current, setCurrent,
    next, setNext,
    repeat, setRepeat,
    status, message, hint, canSubmit,
    submit, reset,
  };
}
