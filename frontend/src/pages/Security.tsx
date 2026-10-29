import React, { useCallback, useEffect, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { Alert, Badge, Button, Card, Modal } from 'flowbite-react';
import { HiShieldCheck, HiShieldExclamation } from 'react-icons/hi';
import { useAuth } from '../contexts/AuthContext';
import { useToast } from '../contexts/ToastContext';
import {
  disableTwoFactor,
  getTwoFactorStatus,
  newRecoveryCodes,
  type TwoFactorStatus,
} from '../api/client';
import { CodeInput, RecoveryCodes, TwoFactorSetupPanel } from '../components/settings/TwoFactor';
import { startReauthFlow, type HandedOffReauthState } from './ReauthComplete';

export const Security: React.FC = () => {
  const location = useLocation();
  const navigate = useNavigate();
  const { setToken } = useAuth();
  const { showToast } = useToast();
  const [status, setStatus] = useState<TwoFactorStatus | null>(null);
  const [settingUp, setSettingUp] = useState(false);
  const [codes, setCodes] = useState<string[] | null>(null);
  // Which code prompt is open: new recovery codes, or turning 2FA off after reauth.
  const [prompt, setPrompt] = useState<'recovery' | 'disable' | null>(null);
  const [reauthToken, setReauthToken] = useState<string | null>(null);
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    getTwoFactorStatus().then(setStatus).catch(() => setStatus(null));
  }, []);
  useEffect(load, [load]);

  // Back from reauthentication to turn two-factor off: ask for a code next.
  useEffect(() => {
    const state = location.state as HandedOffReauthState<'2fa-disable'> | null;
    if (state?.reauthToken && state.action.kind === '2fa-disable') {
      setReauthToken(state.reauthToken);
      setPrompt('disable');
      navigate(location.pathname, { replace: true, state: null });
    }
  }, [location.state, location.pathname, navigate]);

  const closePrompt = () => {
    setPrompt(null);
    setCode('');
    setError(null);
    setReauthToken(null);
  };

  const submitPrompt = async () => {
    setBusy(true);
    setError(null);
    try {
      if (prompt === 'recovery') {
        const r = await newRecoveryCodes(code);
        closePrompt();
        setCodes(r.recovery_codes);
      } else if (prompt === 'disable' && reauthToken) {
        const r = await disableTwoFactor(code, reauthToken);
        closePrompt();
        setToken(r.token);
        showToast('success', 'Two-factor authentication is off');
      }
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      if (prompt === 'disable') setReauthToken(null); // spent once the server checked it
    } finally {
      setBusy(false);
      setCode('');
    }
  };

  const enabled = !!status?.enabled;

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-3xl font-bold">Security</h1>
        <p className="mt-2 text-gray-600 dark:text-gray-400">Protect your account with a second sign-in step.</p>
      </div>

      <Card className="max-w-3xl">
        <h2 className="text-xl font-semibold flex items-center gap-2">
          {enabled ? <HiShieldCheck className="h-5 w-5 text-green-600" /> : <HiShieldExclamation className="h-5 w-5 text-yellow-500" />}
          Two-factor authentication
          {status && (enabled ? <Badge color="success">On</Badge> : <Badge color="warning">Off</Badge>)}
        </h2>
        {!status && <p className="text-gray-500">Loading...</p>}

        {status && !enabled && !settingUp && (
          <>
            <p className="text-gray-600 dark:text-gray-400">
              After signing in, you'll also enter a code from an app on your phone. Someone who gets hold of your
              password still can't get in. <strong>Strongly recommended</strong>, and needed to move this server.
            </p>
            <div><Button onClick={() => setSettingUp(true)}>Set up two-factor</Button></div>
          </>
        )}

        {status && !enabled && settingUp && (
          <TwoFactorSetupPanel
            onDone={(recovery, token) => {
              setSettingUp(false);
              setToken(token); // the old session stops working once two-factor is on
              setCodes(recovery);
              load();
            }}
          />
        )}

        {status && enabled && (
          <>
            <p className="text-gray-600 dark:text-gray-400">
              You enter a code from your authenticator app each time you sign in.
              {' '}{status.recovery_codes_left} recovery code{status.recovery_codes_left === 1 ? '' : 's'} left.
            </p>
            {status.recovery_codes_left <= 2 && (
              <Alert color="warning">You're almost out of recovery codes. Make new ones.</Alert>
            )}
            <div className="flex flex-wrap gap-2">
              <Button color="gray" onClick={() => setPrompt('recovery')}>New recovery codes</Button>
              {!status.required && (
                <Button color="failure" outline
                        onClick={() => startReauthFlow({ kind: '2fa-disable' }).catch((e: Error) =>
                          showToast('error', 'Could not start reauthentication', e.message))}>
                  Turn off
                </Button>
              )}
            </div>
            {status.required && (
              <p className="text-sm text-gray-500 dark:text-gray-400">This server requires two-factor for every account.</p>
            )}
          </>
        )}
      </Card>

      <Modal show={codes !== null} onClose={() => setCodes(null)}>
        <Modal.Header>Recovery codes</Modal.Header>
        <Modal.Body>{codes && <RecoveryCodes codes={codes} />}</Modal.Body>
        <Modal.Footer><Button onClick={() => setCodes(null)}>I've saved them</Button></Modal.Footer>
      </Modal>

      <Modal show={prompt !== null} onClose={closePrompt} size="md">
        <Modal.Header>{prompt === 'disable' ? 'Turn off two-factor' : 'New recovery codes'}</Modal.Header>
        <Modal.Body>
          <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); submitPrompt(); }}>
            {error && <Alert color="failure">{error}</Alert>}
            {prompt === 'recovery' && (
              <p className="text-gray-600 dark:text-gray-400">Your current recovery codes stop working.</p>
            )}
            <CodeInput id="totp-security-code" value={code} onChange={setCode} allowRecovery={prompt === 'disable'} autoFocus />
            <Button type="submit" isProcessing={busy}
                    disabled={busy || code.trim().length < 6 || (prompt === 'disable' && !reauthToken)}>
              Continue
            </Button>
            {prompt === 'disable' && !reauthToken && (
              <p className="text-sm text-gray-500">Close this and choose Turn off again to sign in again.</p>
            )}
          </form>
        </Modal.Body>
      </Modal>
    </div>
  );
};
