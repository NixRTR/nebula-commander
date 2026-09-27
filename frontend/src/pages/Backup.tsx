import React, { useCallback, useEffect, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { Alert, Button, Card, Checkbox, Label, Modal, TextInput } from 'flowbite-react';
import { HiClipboardCopy, HiDownload, HiEye, HiEyeOff, HiLockClosed, HiUpload } from 'react-icons/hi';
import { RequireSystemAdmin } from '../components/permissions/RequireSystemAdmin';
import { useToast } from '../contexts/ToastContext';
import {
  exportInstance,
  getBackupStatus,
  importInstance,
  type BackupStatus,
  type ImportSummary,
} from '../api/client';
import { startReauthFlow, type BackupReauthState } from './ReauthComplete';
import { downloadBlob } from '../utils/download';

/** Rough strength hint only; the server enforces the minimum length. */
function strengthHint(p: string): { label: string; color: string } {
  let score = 0;
  if (p.length >= 16) score++;
  if (p.length >= 24) score++;
  if (/[a-z]/.test(p) && /[A-Z]/.test(p)) score++;
  if (/\d/.test(p)) score++;
  if (/[^A-Za-z0-9]/.test(p) || /\s/.test(p)) score++;
  if (score >= 4) return { label: 'Strong', color: 'text-green-600 dark:text-green-400' };
  if (score >= 2) return { label: 'Fair', color: 'text-yellow-600 dark:text-yellow-400' };
  return { label: 'Weak', color: 'text-red-600 dark:text-red-400' };
}

export const Backup: React.FC = () => {
  const location = useLocation();
  const navigate = useNavigate();
  const { showToast } = useToast();

  const [status, setStatus] = useState<BackupStatus | null>(null);
  const [includeDeviceKey, setIncludeDeviceKey] = useState(true);
  const [starting, setStarting] = useState<'export' | 'import' | null>(null);

  // Set only after a successful reauth; single use and valid for 5 minutes.
  const [reauth, setReauth] = useState<BackupReauthState | null>(null);
  const [passphrase, setPassphrase] = useState('');
  const [confirm, setConfirm] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [summary, setSummary] = useState<ImportSummary | null>(null);
  // Shown once after a successful export so the admin can write the passphrase down;
  // held only in memory and wiped when the dialog closes.
  const [saved, setSaved] = useState<{ passphrase: string; filename: string } | null>(null);
  const [revealed, setRevealed] = useState(false);

  const minLength = status?.min_passphrase_length ?? 12;

  const loadStatus = useCallback(() => {
    getBackupStatus().then(setStatus).catch(() => setStatus(null));
  }, []);

  useEffect(loadStatus, [loadStatus]);

  // Back from reauthentication: take the token out of router history right away.
  useEffect(() => {
    const state = location.state as BackupReauthState | null;
    if (state?.reauthToken) {
      setReauth(state);
      if (state.action.kind === 'instance-export') setIncludeDeviceKey(state.action.includeDeviceKey);
      navigate(location.pathname, { replace: true, state: null });
    }
  }, [location.state, location.pathname, navigate]);

  const closeModal = () => {
    setReauth(null);
    setPassphrase('');
    setConfirm('');
    setFile(null);
    setError(null);
  };

  const begin = async (kind: 'export' | 'import') => {
    setStarting(kind);
    try {
      await startReauthFlow(
        kind === 'export' ? { kind: 'instance-export', includeDeviceKey } : { kind: 'instance-import' }
      );
    } catch (e) {
      setStarting(null);
      showToast('error', 'Could not start reauthentication', e instanceof Error ? e.message : String(e));
    }
  };

  const runExport = async () => {
    if (!reauth) return;
    if (passphrase.length < minLength) return setError(`Use at least ${minLength} characters.`);
    if (passphrase !== confirm) return setError('The passphrases do not match.');
    setBusy(true);
    setError(null);
    try {
      const { blob, filename } = await exportInstance(reauth.reauthToken, passphrase, includeDeviceKey);
      downloadBlob(blob, filename);
      setSaved({ passphrase, filename });
      setRevealed(false);
      closeModal();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      // The reauth token is spent once the server has checked it.
      setReauth(null);
    } finally {
      setBusy(false);
      setPassphrase('');
      setConfirm('');
    }
  };

  const runImport = async () => {
    if (!reauth || !file) return setError('Choose an export file.');
    if (!passphrase) return setError('Enter the passphrase the export was created with.');
    setBusy(true);
    setError(null);
    try {
      const result = await importInstance(reauth.reauthToken, file, passphrase);
      closeModal();
      setSummary(result);
      loadStatus();
      showToast('success', 'Import complete');
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setReauth(null);
    } finally {
      setBusy(false);
      setPassphrase('');
    }
  };

  const closeSaved = () => {
    setSaved(null);
    setRevealed(false);
  };

  const copyPassphrase = async () => {
    if (!saved) return;
    try {
      await navigator.clipboard.writeText(saved.passphrase);
      showToast('success', 'Passphrase copied', 'Paste it into your password manager, then clear your clipboard.');
    } catch {
      showToast('error', 'Could not copy', 'Select the passphrase and copy it manually.');
    }
  };

  const hint = strengthHint(passphrase);
  const isExport = reauth?.action.kind === 'instance-export';
  const tokenSpent = error !== null && reauth === null;

  return (
    <RequireSystemAdmin>
      <div>
        <div className="mb-6">
          <h1 className="text-3xl font-bold">Backup &amp; export</h1>
          <p className="mt-2 text-gray-600 dark:text-gray-400">
            Download everything in this instance as one encrypted file, or move an export from another instance here.
          </p>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <Card>
            <h2 className="text-xl font-semibold flex items-center gap-2">
              <HiDownload className="h-5 w-5" /> Export this instance
            </h2>
            <p className="text-gray-600 dark:text-gray-400">
              Networks, certificate authorities and keys, nodes, groups, firewall rules, DNS, users and permissions,
              invitations and the audit log.
            </p>
            <p className="text-gray-600 dark:text-gray-400 flex gap-2">
              <HiLockClosed className="h-5 w-5 shrink-0 mt-0.5" />
              <span>
                The file is encrypted with a passphrase you choose. Nobody, including whoever runs this server, can
                open it without the passphrase, and it <strong>cannot be recovered</strong> if you lose it. It's a
                standard <a className="underline" href="https://age-encryption.org" target="_blank" rel="noreferrer">age</a> file,
                so you can also open it without Nebula Commander.
              </span>
            </p>
            <div className="flex items-start gap-2">
              <Checkbox id="include-device-key" checked={includeDeviceKey}
                        onChange={(e) => setIncludeDeviceKey(e.target.checked)} />
              <Label htmlFor="include-device-key" className="font-normal">
                Keep enrolled devices working after a move. This includes the key that signs device credentials, so
                devices only need the new server address. Leave it off for a plain backup you won't import elsewhere.
              </Label>
            </div>
            <div>
              <Button onClick={() => begin('export')} isProcessing={starting === 'export'} disabled={starting !== null}>
                Create encrypted export
              </Button>
              <p className="mt-2 text-sm text-gray-500 dark:text-gray-400">You'll be asked to sign in again first.</p>
            </div>
          </Card>

          <Card>
            <h2 className="text-xl font-semibold flex items-center gap-2">
              <HiUpload className="h-5 w-5" /> Import an export
            </h2>
            <p className="text-gray-600 dark:text-gray-400">
              Move an instance here, for example from hosted Nebula Commander to your own server. Import only works on
              a fresh instance with no networks or nodes yet.
            </p>
            {status && !status.can_import ? (
              <Alert color="gray">
                This instance already has {status.networks} network(s) and {status.nodes} node(s), so it can't be
                imported into.
              </Alert>
            ) : (
              <div>
                <Button color="gray" onClick={() => begin('import')} isProcessing={starting === 'import'}
                        disabled={starting !== null || !status}>
                  Import from a file
                </Button>
                <p className="mt-2 text-sm text-gray-500 dark:text-gray-400">
                  You'll sign in again, then choose the file and enter its passphrase.
                </p>
              </div>
            )}
          </Card>
        </div>

        {tokenSpent && (
          <Alert color="failure" className="mt-4" onDismiss={() => setError(null)}>
            {error} To try again, start over (you'll be asked to sign in again).
          </Alert>
        )}

        {summary && (
          <Card className="mt-4">
            <h2 className="text-xl font-semibold">Import complete</h2>
            <p className="text-gray-600 dark:text-gray-400">
              From {summary.source_public_url || 'another instance'}
              {summary.exported_at ? `, exported ${new Date(summary.exported_at).toLocaleString()}` : ''}.
            </p>
            <ul className="list-disc ml-6 text-gray-700 dark:text-gray-300">
              {Object.entries(summary.inserted).map(([table, n]) => (
                <li key={table}>{n} {table.replace(/_/g, ' ')}</li>
              ))}
              <li>{summary.cert_files} certificate and key files</li>
              <li>
                {summary.users_created} user(s) created, {summary.users_matched} matched to existing accounts
              </li>
            </ul>
            {!summary.same_identity_provider && summary.users_created > 0 && (
              <Alert color="info">
                This instance uses a different sign-in provider. Imported users get their access back the first time
                they sign in here with the same email address, once the provider has verified that address.
              </Alert>
            )}
            <div>
              <h3 className="font-semibold">Point your devices at this server</h3>
              {summary.device_key_restored ? (
                <p className="text-gray-600 dark:text-gray-400">
                  Enrolled devices keep working. On each device, change the server address and restart ncclient:
                </p>
              ) : (
                <p className="text-gray-600 dark:text-gray-400">
                  The export didn't include the device signing key, so devices need a new enrollment code from the
                  Nodes page. When enrolling, use:
                </p>
              )}
              <pre className="mt-2 p-3 rounded bg-gray-100 dark:bg-gray-800 text-sm overflow-x-auto">
                NEBULA_COMMANDER_SERVER={status?.public_url || window.location.origin}
              </pre>
            </div>
            {summary.warnings.length > 0 && (
              <Alert color="warning">
                <ul className="list-disc ml-4">
                  {summary.warnings.map((w) => <li key={w}>{w}</li>)}
                </ul>
              </Alert>
            )}
          </Card>
        )}

        <Modal show={saved !== null} onClose={closeSaved} size="md">
          <Modal.Header>Save your passphrase</Modal.Header>
          <Modal.Body>
            <div className="space-y-4">
              <p className="text-gray-700 dark:text-gray-300">
                <strong>{saved?.filename}</strong> has been downloaded. Write down or save this passphrase now.
                Without it the export can't be opened, and it can't be recovered or reset.
              </p>
              <div>
                <Label htmlFor="saved-pass">Export passphrase</Label>
                <div className="flex gap-2 mt-1">
                  <TextInput id="saved-pass" className="flex-1" readOnly autoComplete="off"
                             type={revealed ? 'text' : 'password'} value={saved?.passphrase ?? ''}
                             onFocus={(e) => revealed && e.target.select()} />
                  <Button color="gray" onClick={() => setRevealed((r) => !r)}
                          aria-label={revealed ? 'Hide passphrase' : 'Show passphrase'}>
                    {revealed ? <HiEyeOff className="h-5 w-5" /> : <HiEye className="h-5 w-5" />}
                    <span className="ml-2">{revealed ? 'Hide' : 'Show'}</span>
                  </Button>
                  <Button color="gray" onClick={copyPassphrase} aria-label="Copy passphrase">
                    <HiClipboardCopy className="h-5 w-5" />
                    <span className="ml-2">Copy</span>
                  </Button>
                </div>
              </div>
              <p className="text-sm text-gray-500 dark:text-gray-400">
                The passphrase isn't stored anywhere. Once you close this window it's gone from this page too.
              </p>
            </div>
          </Modal.Body>
          <Modal.Footer>
            <Button onClick={closeSaved}>I've saved it</Button>
          </Modal.Footer>
        </Modal>

        <Modal show={reauth !== null} onClose={busy ? () => undefined : closeModal} size="md">
          <Modal.Header>{isExport ? 'Choose a passphrase' : 'Import an export'}</Modal.Header>
          <Modal.Body>
            <div className="space-y-4">
              {isExport ? (
                <>
                  <p className="text-gray-700 dark:text-gray-300">
                    The export is encrypted with this passphrase. Store it in a password manager: without it the file
                    can't be opened, by you or anyone else.
                  </p>
                  <div>
                    <Label htmlFor="export-pass">Passphrase (at least {minLength} characters)</Label>
                    <TextInput id="export-pass" type="password" autoComplete="new-password" value={passphrase}
                               onChange={(e) => setPassphrase(e.target.value)} disabled={busy} autoFocus />
                    {passphrase && <p className={`mt-1 text-sm ${hint.color}`}>{hint.label}</p>}
                  </div>
                  <div>
                    <Label htmlFor="export-pass2">Repeat passphrase</Label>
                    <TextInput id="export-pass2" type="password" autoComplete="new-password" value={confirm}
                               onChange={(e) => setConfirm(e.target.value)} disabled={busy}
                               onKeyDown={(e) => e.key === 'Enter' && runExport()} />
                  </div>
                </>
              ) : (
                <>
                  <p className="text-gray-700 dark:text-gray-300">
                    Everything in the export is added to this instance. Existing users stay as they are.
                  </p>
                  <div>
                    <Label htmlFor="import-file">Export file (.ncexport.age)</Label>
                    <input id="import-file" type="file" accept=".age,.ncexport,application/octet-stream"
                           className="block w-full text-sm text-gray-700 dark:text-gray-300 mt-1"
                           onChange={(e) => setFile(e.target.files?.[0] ?? null)} disabled={busy} />
                  </div>
                  <div>
                    <Label htmlFor="import-pass">Passphrase</Label>
                    <TextInput id="import-pass" type="password" autoComplete="off" value={passphrase}
                               onChange={(e) => setPassphrase(e.target.value)} disabled={busy}
                               onKeyDown={(e) => e.key === 'Enter' && runImport()} />
                  </div>
                </>
              )}
              {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}
              <p className="text-xs text-gray-500 dark:text-gray-400">
                This step expires 5 minutes after you signed in again.
              </p>
            </div>
          </Modal.Body>
          <Modal.Footer>
            <Button onClick={isExport ? runExport : runImport} isProcessing={busy} disabled={busy}>
              {isExport ? 'Encrypt and download' : 'Import'}
            </Button>
            <Button color="gray" onClick={closeModal} disabled={busy}>Cancel</Button>
          </Modal.Footer>
        </Modal>
      </div>
    </RequireSystemAdmin>
  );
};
