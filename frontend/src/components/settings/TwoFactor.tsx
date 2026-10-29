/**
 * Shared two-factor pieces: setup (QR + secret + first code), recovery codes, and a
 * code input. Used by the Security page and the login's two-factor step.
 */
import React, { useEffect, useState } from 'react';
import { Alert, Button, Label, TextInput } from 'flowbite-react';
import { HiClipboardCopy, HiDownload } from 'react-icons/hi';
import QRCode from 'qrcode';
import { confirmTwoFactor, startTwoFactorSetup, type TwoFactorSetup } from '../../api/client';
import { downloadBlob } from '../../utils/download';

export const APP_HINT =
  'Any authenticator app works: Aegis, 2FAS, Google or Microsoft Authenticator, Authy, Bitwarden, 1Password, and so on.';

export const CodeInput: React.FC<{
  id: string;
  value: string;
  onChange: (v: string) => void;
  allowRecovery?: boolean;
  autoFocus?: boolean;
}> = ({ id, value, onChange, allowRecovery = false, autoFocus = false }) => (
  <div>
    <Label htmlFor={id} value={allowRecovery ? '6-digit code, or a recovery code' : '6-digit code from your app'} />
    <TextInput
      id={id}
      value={value}
      autoFocus={autoFocus}
      autoComplete="one-time-code"
      inputMode={allowRecovery ? 'text' : 'numeric'}
      placeholder={allowRecovery ? '123456 or ABCDE-FGHJK' : '123456'}
      maxLength={allowRecovery ? 11 : 6}
      onChange={(e) => onChange(allowRecovery ? e.target.value : e.target.value.replace(/\D/g, ''))}
      className="mt-1 font-mono"
    />
  </div>
);

/** Scan, then confirm with a first code. onDone gets the recovery codes and the new session token. */
export const TwoFactorSetupPanel: React.FC<{
  token?: string;
  onDone: (recoveryCodes: string[], sessionToken: string) => void;
}> = ({ token, onDone }) => {
  const [setup, setSetup] = useState<TwoFactorSetup | null>(null);
  const [qr, setQr] = useState<string | null>(null);
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    startTwoFactorSetup(token)
      .then(async (s) => {
        if (cancelled) return;
        setSetup(s);
        setQr(await QRCode.toDataURL(s.otpauth_uri, { margin: 1, width: 220 }));
      })
      .catch((e: Error) => !cancelled && setError(e.message));
    return () => {
      cancelled = true;
    };
  }, [token]);

  const confirm = async () => {
    setBusy(true);
    setError(null);
    try {
      const r = await confirmTwoFactor(code, token);
      onDone(r.recovery_codes, r.token);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  // Grouped in fours so it can be typed in by hand.
  const grouped = setup?.secret.replace(/(.{4})/g, '$1 ').trim();

  return (
    <div className="space-y-4">
      <p className="text-gray-600 dark:text-gray-400">{APP_HINT}</p>
      {error && <Alert color="failure">{error}</Alert>}
      {setup && (
        <div className="flex flex-col sm:flex-row gap-4 items-start">
          {qr && <img src={qr} alt="QR code for your authenticator app" className="w-[220px] h-[220px] rounded bg-white p-1" />}
          <div className="space-y-2 min-w-0">
            <p className="text-sm text-gray-600 dark:text-gray-400">1. Scan the code with your app, or enter this key:</p>
            <code className="block break-all font-mono text-sm bg-gray-100 dark:bg-gray-800 rounded px-2 py-1">{grouped}</code>
            <p className="text-sm text-gray-600 dark:text-gray-400">2. Enter the code your app shows:</p>
            <CodeInput id="totp-setup-code" value={code} onChange={setCode} autoFocus />
            <Button onClick={confirm} isProcessing={busy} disabled={busy || code.length !== 6}>
              Turn on two-factor
            </Button>
          </div>
        </div>
      )}
    </div>
  );
};

export const RecoveryCodes: React.FC<{ codes: string[] }> = ({ codes }) => {
  const [copied, setCopied] = useState(false);
  const text = codes.join('\n');
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  };
  return (
    <div className="space-y-3">
      <p className="text-gray-600 dark:text-gray-400">
        Each code signs you in once if you lose your phone. Keep them somewhere safe, like a password manager.
        They won't be shown again.
      </p>
      <div className="grid grid-cols-2 gap-2 font-mono text-sm bg-gray-100 dark:bg-gray-800 rounded p-3">
        {codes.map((c) => <span key={c}>{c}</span>)}
      </div>
      <div className="flex flex-wrap gap-2">
        <Button color="gray" size="sm" onClick={copy}>
          <HiClipboardCopy className="mr-2 h-4 w-4" /> {copied ? 'Copied' : 'Copy'}
        </Button>
        <Button color="gray" size="sm"
                onClick={() => downloadBlob(new Blob([text + '\n'], { type: 'text/plain' }), 'nebula-commander-recovery-codes.txt')}>
          <HiDownload className="mr-2 h-4 w-4" /> Download
        </Button>
      </div>
    </div>
  );
};
