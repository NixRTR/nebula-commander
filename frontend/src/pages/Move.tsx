import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { Alert, Badge, Button, Card, Label, Modal, Table, TextInput } from 'flowbite-react';
import { HiClipboardCopy, HiDownload, HiSwitchHorizontal } from 'react-icons/hi';
import { RequireSystemAdmin } from '../components/permissions/RequireSystemAdmin';
import { CodeInput } from '../components/settings/TwoFactor';
import { useAuth } from '../contexts/AuthContext';
import { useToast } from '../contexts/ToastContext';
import {
  cancelMove,
  downloadMoveResponder,
  getMoveStatus,
  startMove,
  type MoveNode,
  type MoveStatus,
  type StartMoveForm,
} from '../api/client';
import { downloadBlob } from '../utils/download';
import { startReauthFlow, type HandedOffReauthState } from './ReauthComplete';

const SECOND_LEVEL = ['co', 'com', 'org', 'net', 'ac', 'gov', 'edu'];

/** Same heuristic as backend/api/move.py and client/server_move.py. */
function registrableDomain(url: string): string | null {
  let host = '';
  try {
    host = new URL(url.includes('://') ? url : `https://${url}`).hostname.toLowerCase();
  } catch {
    return null;
  }
  if (/^[\d.]+$/.test(host) || host.startsWith('[')) return null;
  const labels = host.split('.').filter(Boolean);
  if (labels.length < 2) return host || null;
  if (labels.length >= 3 && labels[labels.length - 1].length === 2 && SECOND_LEVEL.includes(labels[labels.length - 2])) {
    return labels.slice(-3).join('.');
  }
  return labels.slice(-2).join('.');
}

function fmt(iso: string | null | undefined): string {
  return iso ? new Date(iso).toLocaleString() : '-';
}

function versionAtLeast(v: string | null, min: string): boolean {
  if (!v) return false;
  const a = v.split(/[.+-]/).map((x) => parseInt(x, 10) || 0);
  const b = min.split('.').map((x) => parseInt(x, 10) || 0);
  for (let i = 0; i < 3; i++) {
    if ((a[i] ?? 0) !== b[i]) return (a[i] ?? 0) > b[i];
  }
  return true;
}

function nodeState(n: MoveNode, minVersion: string): { label: string; color: string } {
  if (n.move_state === 'switching') return { label: 'Moved', color: 'success' };
  if (n.move_state === 'failed') return { label: 'Problem', color: 'failure' };
  if (n.move_state === 'pending') return { label: 'Waiting', color: 'info' };
  if (n.move_ready) return { label: 'Ready', color: 'success' };
  if (n.client_version && !versionAtLeast(n.client_version, minVersion) && !n.client_version.startsWith('0.0.0')) {
    return { label: 'Client too old', color: 'warning' };
  }
  return { label: 'Not ready', color: 'warning' };
}

export const Move: React.FC = () => {
  const location = useLocation();
  const navigate = useNavigate();
  const { refresh } = useAuth();
  const { showToast } = useToast();
  const [status, setStatus] = useState<MoveStatus | null>(null);
  const [form, setForm] = useState<StartMoveForm>({ new_url: '', new_key_fp: '', wait_hours: 24, keep_days: 30, expires_days: 365 });
  const [pending, setPending] = useState<HandedOffReauthState<'move-start' | 'move-cancel'> | null>(null);
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    getMoveStatus().then((s) => {
      setStatus(s);
      setForm((f) => (f.new_url ? f : { ...f, wait_hours: s.default_wait_hours }));
    }).catch(() => setStatus(null));
  }, []);
  useEffect(load, [load]);
  // Progress while a move runs
  useEffect(() => {
    if (!status?.move) return;
    const t = window.setInterval(load, 30000);
    return () => window.clearInterval(t);
  }, [status?.move, load]);

  // Back from reauthentication: the two-factor code is asked for next.
  useEffect(() => {
    const state = location.state as HandedOffReauthState<'move-start' | 'move-cancel'> | null;
    if (state?.reauthToken && (state.action.kind === 'move-start' || state.action.kind === 'move-cancel')) {
      setPending(state);
      if (state.action.kind === 'move-start') setForm(state.action.form);
      navigate(location.pathname, { replace: true, state: null });
    }
  }, [location.state, location.pathname, navigate]);

  const crossDomain = useMemo(() => {
    if (!status || !form.new_url) return false;
    const own = registrableDomain(status.public_url);
    const target = registrableDomain(form.new_url);
    return !own || !target || own !== target;
  }, [status, form.new_url]);

  const copy = async (text: string, what: string) => {
    try {
      await navigator.clipboard.writeText(text);
      showToast('success', `${what} copied`);
    } catch {
      showToast('error', 'Could not copy', 'Select it and copy it manually.');
    }
  };

  const begin = (kind: 'move-start' | 'move-cancel') => {
    const action = kind === 'move-start' ? { kind, form } as const : { kind } as const;
    startReauthFlow(action).catch((e: Error) => showToast('error', 'Could not start reauthentication', e.message));
  };

  const closePending = () => {
    setPending(null);
    setCode('');
    setError(null);
  };

  const submit = async () => {
    if (!pending) return;
    setBusy(true);
    setError(null);
    try {
      if (pending.action.kind === 'move-start') {
        await startMove(pending.action.form, pending.reauthToken, code);
        showToast('success', 'Move started', 'Devices will switch after the wait.');
      } else {
        await cancelMove(pending.reauthToken, code);
        showToast('success', 'Move cancelled');
      }
      closePending();
      load();
      refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setPending(null); // the reauth token is spent once the server has checked it
    } finally {
      setBusy(false);
      setCode('');
    }
  };

  const responder = async () => {
    try {
      downloadBlob(await downloadMoveResponder(), 'move-responder.json');
    } catch (e) {
      showToast('error', 'Download failed', e instanceof Error ? e.message : String(e));
    }
  };

  const move = status?.move;
  const nodes = status?.nodes ?? [];
  const ready = nodes.filter((n) => n.move_ready).length;
  const moved = nodes.filter((n) => n.move_state === 'switching').length;
  const formValid = form.new_url.trim() && form.new_key_fp.trim().length >= 20;

  return (
    <RequireSystemAdmin>
      <div>
        <div className="mb-6">
          <h1 className="text-3xl font-bold">Move server</h1>
          <p className="mt-2 text-gray-600 dark:text-gray-400">
            Point every device at another Nebula Commander server, for example your own after leaving a hosted one.
            Devices switch by themselves; nobody has to touch them.
          </p>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <Card>
            <h2 className="text-xl font-semibold">This server's fingerprint</h2>
            <p className="text-gray-600 dark:text-gray-400">
              Moving <strong>to</strong> this server? Paste this into the Move server page of the server you're leaving.
            </p>
            {status && (
              <div className="flex gap-2 items-center min-w-0">
                <code className="flex-1 min-w-0 break-all font-mono text-sm bg-gray-100 dark:bg-gray-800 rounded px-2 py-1">
                  {status.fingerprint}
                </code>
                <Button color="gray" size="sm" onClick={() => copy(status.fingerprint, 'Fingerprint')}>
                  <HiClipboardCopy className="h-4 w-4" />
                </Button>
              </div>
            )}
          </Card>

          <Card>
            <h2 className="text-xl font-semibold">How a move works</h2>
            <ol className="list-decimal ml-5 space-y-1 text-gray-600 dark:text-gray-400">
              <li>On <Link className="underline" to="/settings/backup">Backup &amp; export</Link>, export with "Keep enrolled devices working" on, and import it into the new server.</li>
              <li>Copy the new server's fingerprint and start the move here.</li>
              <li>Devices show a notice, wait, check the new server is the real one, then switch.</li>
              <li>This server stays read-only meanwhile. Afterwards, keep its address answering (see below).</li>
            </ol>
          </Card>
        </div>

        {status && !status.two_factor_enabled && !move && (
          <Alert color="warning" className="mt-4">
            Moving a server needs two-factor authentication on your account.{' '}
            <Link className="underline font-medium" to="/settings/security">Set it up on the Security page.</Link>
          </Alert>
        )}

        {status && !move && (
          <Card className="mt-4">
            <h2 className="text-xl font-semibold flex items-center gap-2"><HiSwitchHorizontal className="h-5 w-5" /> Start a move</h2>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <Label htmlFor="move-url" value="New server address" />
                <TextInput id="move-url" className="mt-1" placeholder="https://nc.example.com"
                           value={form.new_url} onChange={(e) => setForm({ ...form, new_url: e.target.value })} />
              </div>
              <div>
                <Label htmlFor="move-fp" value="New server's fingerprint" />
                <TextInput id="move-fp" className="mt-1 font-mono" placeholder="SHA256:..."
                           value={form.new_key_fp} onChange={(e) => setForm({ ...form, new_key_fp: e.target.value })} />
              </div>
              <div>
                <Label htmlFor="move-wait" value="Devices wait before switching (hours)" />
                <TextInput id="move-wait" type="number" className="mt-1" min={status.min_wait_hours} max={status.max_wait_hours}
                           value={form.wait_hours} onChange={(e) => setForm({ ...form, wait_hours: Number(e.target.value) })} />
                <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
                  Time for anyone to notice and cancel a move they didn't expect.
                </p>
              </div>
              <div>
                <Label htmlFor="move-keep" value="Keep this address answering for (days)" />
                <TextInput id="move-keep" type="number" className="mt-1" min={1} max={365}
                           value={form.keep_days} onChange={(e) => setForm({ ...form, keep_days: Number(e.target.value) })} />
                <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
                  So devices that are switched off for a while still find the new server.
                </p>
              </div>
            </div>
            {crossDomain && form.new_url && (
              <Alert color="info">
                That's a different domain or an IP address. Devices then wait at least {status.client_foreign_floor_hours} hours,
                whatever you set, and tell their users they're moving to a different provider.
              </Alert>
            )}
            {nodes.length > 0 && ready < nodes.length && (
              <Alert color="warning">
                {ready} of {nodes.length} devices are ready to follow a move. The others need Nebula Commander client{' '}
                {status.move_client_version} or newer and one check-in after updating, or must be pointed at the new
                server by hand.
              </Alert>
            )}
            <div>
              <Button onClick={() => begin('move-start')} disabled={!status.two_factor_enabled || !formValid}>
                Start move
              </Button>
              <p className="mt-2 text-sm text-gray-500 dark:text-gray-400">
                You'll sign in again and enter a two-factor code.
              </p>
            </div>
          </Card>
        )}

        {move && (
          <Card className="mt-4">
            <h2 className="text-xl font-semibold flex items-center gap-2">
              Moving to <a className="underline break-all" href={move.new_url} target="_blank" rel="noreferrer">{move.new_url}</a>
            </h2>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-2 text-sm text-gray-600 dark:text-gray-400">
              <div>Started: {fmt(move.created_at)}</div>
              <div>Devices switch from: {fmt(move.switch_at)}</div>
              <div>Keep this address answering until: {fmt(move.recommended_until)}</div>
            </div>
            <p className="text-gray-600 dark:text-gray-400">{moved} of {nodes.length} devices have moved.</p>
            <div className="overflow-x-auto">
              <Table>
                <Table.Head>
                  <Table.HeadCell>Device</Table.HeadCell>
                  <Table.HeadCell>Network</Table.HeadCell>
                  <Table.HeadCell>Client</Table.HeadCell>
                  <Table.HeadCell>State</Table.HeadCell>
                  <Table.HeadCell>Last seen here</Table.HeadCell>
                </Table.Head>
                <Table.Body className="divide-y">
                  {nodes.map((n) => {
                    const st = nodeState(n, status!.move_client_version);
                    return (
                      <Table.Row key={n.id}>
                        <Table.Cell className="font-medium">{n.hostname}</Table.Cell>
                        <Table.Cell>{n.network}</Table.Cell>
                        <Table.Cell>{n.client_version ?? '-'}</Table.Cell>
                        <Table.Cell>
                          <Badge color={st.color} className="w-fit">{st.label}</Badge>
                          {n.move_error && <div className="text-xs text-red-600 dark:text-red-400 mt-1">{n.move_error}</div>}
                        </Table.Cell>
                        <Table.Cell>{fmt(n.last_seen)}</Table.Cell>
                      </Table.Row>
                    );
                  })}
                </Table.Body>
              </Table>
            </div>
            <div className="space-y-2 text-gray-600 dark:text-gray-400">
              <h3 className="font-semibold text-gray-900 dark:text-white">After the move</h3>
              <p>
                Download the responder file and restart this server's backend with
                {' '}<code className="text-sm">NEBULA_COMMANDER_MOVED_ONLY_FILE=/path/move-responder.json</code>.
                It then only points devices at the new server. Once the period above is over, admins get an email with a
                tiny standalone responder, so this domain can be used for something else.
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button color="gray" onClick={responder}><HiDownload className="mr-2 h-4 w-4" /> Responder file</Button>
              <Button color="failure" outline onClick={() => begin('move-cancel')}>Cancel move</Button>
            </div>
          </Card>
        )}

        <Modal show={pending !== null || error !== null} onClose={closePending} size="md">
          <Modal.Header>{pending?.action.kind === 'move-cancel' ? 'Cancel the move' : 'Start the move'}</Modal.Header>
          <Modal.Body>
            <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); submit(); }}>
              {error && <Alert color="failure">{error}</Alert>}
              {pending ? (
                <>
                  {pending.action.kind === 'move-start' && (
                    <p className="text-gray-600 dark:text-gray-400 break-all">
                      Devices will move to <strong>{pending.action.form.new_url}</strong>.
                    </p>
                  )}
                  <CodeInput id="totp-move-code" value={code} onChange={setCode} allowRecovery autoFocus />
                  <Button type="submit" isProcessing={busy} disabled={busy || code.trim().length < 6}>Confirm</Button>
                </>
              ) : (
                <Button color="gray" onClick={closePending}>Close</Button>
              )}
            </form>
          </Modal.Body>
        </Modal>
      </div>
    </RequireSystemAdmin>
  );
};
