/**
 * The second step of a login that owes a second factor (backend/auth/mfa.py): enter a
 * code, or - when the instance requires two-factor and this account has none yet - set
 * it up. The pending token from the login lives only in sessionStorage.
 */
import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Alert, Button } from 'flowbite-react';
import { useAuth } from '../contexts/AuthContext';
import {
  clearPendingMfaToken,
  getPendingMfaToken,
  getTwoFactorStatus,
  verifyTwoFactor,
} from '../api/client';
import { CodeInput, RecoveryCodes, TwoFactorSetupPanel } from '../components/settings/TwoFactor';

const TwoFactorLogin: React.FC = () => {
  const { setToken } = useAuth();
  const navigate = useNavigate();
  const pending = getPendingMfaToken();
  const [mode, setMode] = useState<'loading' | 'verify' | 'setup' | 'codes'>('loading');
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [codes, setCodes] = useState<string[]>([]);
  const [fullToken, setFullToken] = useState<string | null>(null);

  useEffect(() => {
    if (!pending) {
      navigate('/login', { replace: true });
      return;
    }
    getTwoFactorStatus(pending)
      .then((s) => setMode(s.login_state === 'setup' ? 'setup' : 'verify'))
      .catch(() => {
        clearPendingMfaToken();
        navigate('/login?error=auth_failed', { replace: true });
      });
  }, [pending, navigate]);

  const finish = (token: string) => {
    clearPendingMfaToken();
    setToken(token);
    const returnUrl = localStorage.getItem('invitation_return_url');
    if (returnUrl) localStorage.removeItem('invitation_return_url');
    navigate(returnUrl || '/', { replace: true });
  };

  const verify = async () => {
    if (!pending) return;
    setBusy(true);
    setError(null);
    try {
      const r = await verifyTwoFactor(code, pending);
      finish(r.token);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setCode('');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className="relative min-h-screen flex items-center justify-center bg-gray-900 bg-cover bg-center bg-no-repeat px-4"
      style={{ backgroundImage: 'url(/nebula.webp)' }}
    >
      <div className="absolute inset-0 bg-black/50" aria-hidden="true" />
      <div className="relative z-10 max-w-xl w-full space-y-6 p-8 bg-white dark:bg-gray-800 rounded-lg shadow-xl">
        <div>
          <img src="/logo.svg" alt="Nebula Commander" className="h-12 w-auto" />
          <h2 className="mt-4 text-2xl font-bold text-gray-900 dark:text-white">
            {mode === 'setup' ? 'Set up two-factor authentication' : mode === 'codes' ? 'Save your recovery codes' : 'Two-factor authentication'}
          </h2>
          {mode === 'setup' && (
            <p className="mt-2 text-gray-600 dark:text-gray-400">This server requires a second sign-in step for every account.</p>
          )}
        </div>
        {mode === 'verify' && (
          <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); verify(); }}>
            {error && <Alert color="failure">{error}</Alert>}
            <CodeInput id="totp-login-code" value={code} onChange={setCode} allowRecovery autoFocus />
            <div className="flex gap-2">
              <Button type="submit" isProcessing={busy} disabled={busy || code.trim().length < 6}>Continue</Button>
              <Button color="gray" onClick={() => { clearPendingMfaToken(); navigate('/login', { replace: true }); }}>
                Cancel
              </Button>
            </div>
            <p className="text-sm text-gray-500 dark:text-gray-400">
              Lost your phone? Use one of your recovery codes, or ask an administrator to reset two-factor for your account.
            </p>
          </form>
        )}
        {mode === 'setup' && pending && (
          <TwoFactorSetupPanel
            token={pending}
            onDone={(recovery, token) => { setCodes(recovery); setFullToken(token); setMode('codes'); }}
          />
        )}
        {mode === 'codes' && (
          <div className="space-y-4">
            <RecoveryCodes codes={codes} />
            <Button onClick={() => fullToken && finish(fullToken)}>I've saved them, continue</Button>
          </div>
        )}
        {mode === 'loading' && <p className="text-gray-500">Loading...</p>}
      </div>
    </div>
  );
};

export default TwoFactorLogin;
