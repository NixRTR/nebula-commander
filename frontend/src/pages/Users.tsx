import React, { useState, useEffect } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { Alert, Card, Badge, Button, Modal, Label, Select, TextInput } from 'flowbite-react';
import { HiPencil, HiTrash } from 'react-icons/hi';
import { RequireSystemAdmin } from '../components/permissions/RequireSystemAdmin';
import { CodeInput } from '../components/settings/TwoFactor';
import { useToast } from '../contexts/ToastContext';
import { apiClient, resetUserTwoFactor } from '../api/client';
import { startReauthFlow, type HandedOffReauthState } from './ReauthComplete';

interface User {
  id: number;
  email: string;
  system_role: string;
  network_count: number;
  created_at: string;
  two_factor_enabled?: boolean;
}

interface UserDetail extends User {
  networks: Array<{
    id: number;
    name: string;
    role: string;
    can_manage_nodes: boolean;
    can_invite_users: boolean;
    can_manage_firewall: boolean;
  }>;
}

export const Users: React.FC = () => {
  const [users, setUsers] = useState<User[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedUser, setSelectedUser] = useState<UserDetail | null>(null);
  const [showDetailsModal, setShowDetailsModal] = useState(false);
  const [isEditingRole, setIsEditingRole] = useState(false);
  const [editingRole, setEditingRole] = useState('');
  const [savingRole, setSavingRole] = useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [userToDelete, setUserToDelete] = useState<User | null>(null);
  const [deleteStep, setDeleteStep] = useState<1 | 2>(1);
  const [typedEmail, setTypedEmail] = useState('');
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);
  // Resetting another user's two-factor: back from reauth, the admin's own code is asked for.
  const location = useLocation();
  const navigate = useNavigate();
  const { showToast } = useToast();
  const [reset, setReset] = useState<HandedOffReauthState<'2fa-reset'> | null>(null);
  const [resetCode, setResetCode] = useState('');
  const [resetError, setResetError] = useState<string | null>(null);
  const [resetting, setResetting] = useState(false);

  useEffect(() => {
    const state = location.state as HandedOffReauthState<'2fa-reset'> | null;
    if (state?.reauthToken && state.action.kind === '2fa-reset') {
      setReset(state);
      navigate(location.pathname, { replace: true, state: null });
    }
  }, [location.state, location.pathname, navigate]);

  const submitReset = async () => {
    if (!reset) return;
    setResetting(true);
    setResetError(null);
    try {
      await resetUserTwoFactor(reset.action.userId, resetCode, reset.reauthToken);
      showToast('success', 'Two-factor reset', `${reset.action.email} sets it up again at their next sign-in.`);
      setReset(null);
      setUsers((prev) => prev.map((u) => (u.id === reset.action.userId ? { ...u, two_factor_enabled: false } : u)));
    } catch (e) {
      setResetError(e instanceof Error ? e.message : String(e));
      setReset(null);
    } finally {
      setResetting(false);
      setResetCode('');
    }
  };

  useEffect(() => {
    fetchUsers();
  }, []);

  const fetchUsers = async () => {
    try {
      setLoading(true);
      const response = await apiClient.get('/users');
      setUsers(response.data);
    } catch (error) {
      console.error('Failed to fetch users:', error);
    } finally {
      setLoading(false);
    }
  };

  const fetchUserDetails = async (userId: number) => {
    try {
      const response = await apiClient.get(`/users/${userId}`);
      setSelectedUser(response.data);
      setIsEditingRole(false);
      setShowDetailsModal(true);
    } catch (error) {
      console.error('Failed to fetch user details:', error);
    }
  };

  const handleStartEditRole = () => {
    if (!selectedUser) return;
    setEditingRole(selectedUser.system_role);
    setIsEditingRole(true);
  };

  const handleSaveRole = async () => {
    if (!selectedUser) return;
    setSavingRole(true);
    try {
      await apiClient.patch(`/users/${selectedUser.id}`, {
        system_role: editingRole,
      });
      setIsEditingRole(false);
      await fetchUserDetails(selectedUser.id);
      fetchUsers();
    } catch (error) {
      console.error('Failed to update user role:', error);
      alert('Failed to update user role');
    } finally {
      setSavingRole(false);
    }
  };

  const closeDeleteConfirm = () => {
    setShowDeleteConfirm(false);
    setUserToDelete(null);
    setDeleteStep(1);
    setTypedEmail('');
    setDeleteError(null);
  };

  const openDeleteConfirm = (user: User) => {
    setUserToDelete(user);
    setDeleteStep(1);
    setTypedEmail('');
    setDeleteError(null);
    setShowDeleteConfirm(true);
  };

  const handleDeleteUser = async () => {
    if (!userToDelete) return;
    setDeleting(true);
    setDeleteError(null);
    try {
      await startReauthFlow({
        kind: 'user-delete',
        userId: userToDelete.id,
        email: userToDelete.email,
      });
    } catch (error) {
      setDeleteError(error instanceof Error ? error.message : 'Failed to start reauthentication');
      setDeleting(false);
    }
  };

  const getRoleBadgeColor = (role: string) => {
    switch (role) {
      case 'system-admin':
        return 'failure';
      default:
        return 'gray';
    }
  };

  return (
    <RequireSystemAdmin>
      <div>
        <div className="mb-6">
          <h1 className="text-3xl font-bold">User Management</h1>
          <p className="mt-2 text-gray-600 dark:text-gray-400">Manage system users and their roles</p>
        </div>

        {loading ? (
          <Card>
            <p className="text-gray-600 dark:text-gray-400">Loading users...</p>
          </Card>
        ) : users.length === 0 ? (
          <Card>
            <div className="p-8 text-center">
              <p className="text-gray-500 dark:text-gray-400">No users found.</p>
            </div>
          </Card>
        ) : (
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-4">
            {users.map((user) => (
              <button
                key={user.id}
                type="button"
                onClick={() => fetchUserDetails(user.id)}
                className="relative aspect-square rounded-lg border border-gray-200 dark:border-gray-700 bg-[var(--nc-bg2-light)] dark:bg-[var(--nc-bg2-dark)] p-4 text-left shadow-sm hover:shadow-md transition-shadow flex flex-col"
              >
                <p
                  className="font-semibold text-[var(--nc-bg2-light-contrast)] dark:text-[var(--nc-bg2-dark-contrast)] truncate pr-1"
                  title={user.email || 'N/A'}
                >
                  {user.email || 'N/A'}
                </p>
                <div className="mt-1">
                  <Badge color={getRoleBadgeColor(user.system_role)} size="sm">
                    {user.system_role}
                  </Badge>
                </div>
                <div className="mt-1">
                  <Badge color={user.two_factor_enabled ? 'success' : 'warning'} size="sm">
                    {user.two_factor_enabled ? '2FA on' : 'No 2FA'}
                  </Badge>
                </div>
                <div className="mt-auto">
                  <div className="text-xs text-gray-500 dark:text-gray-400">Networks</div>
                  <div className="font-semibold text-[var(--nc-bg2-light-contrast)] dark:text-[var(--nc-bg2-dark-contrast)]">{user.network_count}</div>
                </div>
              </button>
            ))}
          </div>
        )}

        {/* User Details Modal - view + inline role edit + delete trigger */}
        <Modal show={showDetailsModal && selectedUser !== null} onClose={() => setShowDetailsModal(false)}>
          <Modal.Header>User Details</Modal.Header>
          <Modal.Body>
            {selectedUser && (
              <div className="space-y-4">
                <div>
                  <Label value="Email" />
                  <p className="text-sm text-[var(--nc-bg2-light-contrast)] dark:text-[var(--nc-bg2-dark-contrast)]">{selectedUser.email || 'N/A'}</p>
                </div>
                <div>
                  <Label value="System Role" />
                  {isEditingRole ? (
                    <div className="flex items-center gap-2 mt-1">
                      <Select
                        id="role"
                        value={editingRole}
                        onChange={(e) => setEditingRole(e.target.value)}
                        className="flex-1"
                      >
                        <option value="user">User</option>
                        <option value="system-admin">System Admin</option>
                      </Select>
                      <Button size="sm" onClick={handleSaveRole} isProcessing={savingRole} disabled={savingRole}>
                        Save
                      </Button>
                      <Button size="sm" color="gray" onClick={() => setIsEditingRole(false)} disabled={savingRole}>
                        Cancel
                      </Button>
                    </div>
                  ) : (
                    <div className="flex items-center gap-2 mt-1">
                      <p className="text-sm text-[var(--nc-bg2-light-contrast)] dark:text-[var(--nc-bg2-dark-contrast)]">{selectedUser.system_role}</p>
                      <Button size="xs" color="gray" onClick={handleStartEditRole}>
                        <HiPencil className="mr-1 h-3.5 w-3.5" />
                        Edit
                      </Button>
                    </div>
                  )}
                </div>
                <div>
                  <Label value="Created" />
                  <p className="text-sm text-[var(--nc-bg2-light-contrast)] dark:text-[var(--nc-bg2-dark-contrast)]">
                    {new Date(selectedUser.created_at).toLocaleString()}
                  </p>
                </div>

                {selectedUser.networks && selectedUser.networks.length > 0 && (
                  <div>
                    <Label value="Network Permissions" />
                    <div className="mt-2 space-y-2">
                      {selectedUser.networks.map((network) => (
                        <Card key={network.id}>
                          <h5 className="text-sm font-bold text-[var(--nc-bg2-light-contrast)] dark:text-[var(--nc-bg2-dark-contrast)]">
                            {network.name}
                          </h5>
                          <p className="text-sm text-gray-700 dark:text-gray-400">
                            Role: <Badge color="info" size="sm">{network.role}</Badge>
                          </p>
                          <div className="flex flex-wrap gap-1 mt-2">
                            {network.can_manage_nodes && (
                              <Badge color="success" size="sm">Manage Nodes</Badge>
                            )}
                            {network.can_invite_users && (
                              <Badge color="info" size="sm">Invite Users</Badge>
                            )}
                            {network.can_manage_firewall && (
                              <Badge color="purple" size="sm">Manage Firewall</Badge>
                            )}
                          </div>
                        </Card>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </Modal.Body>
          <Modal.Footer className="justify-between">
            <Button color="gray" onClick={() => setShowDetailsModal(false)}>
              Close
            </Button>
            {selectedUser && users.find((u) => u.id === selectedUser.id)?.two_factor_enabled && (
              <Button
                color="gray"
                onClick={() =>
                  startReauthFlow({ kind: '2fa-reset', userId: selectedUser.id, email: selectedUser.email }).catch(
                    (e: Error) => showToast('error', 'Could not start reauthentication', e.message)
                  )
                }
              >
                Reset 2FA
              </Button>
            )}
            {selectedUser && (
              <Button
                color="failure"
                onClick={() => {
                  setShowDetailsModal(false);
                  openDeleteConfirm(selectedUser);
                }}
              >
                <HiTrash className="mr-1 h-4 w-4" />
                Delete User
              </Button>
            )}
          </Modal.Footer>
        </Modal>

        <Modal show={reset !== null || resetError !== null} onClose={() => { setReset(null); setResetError(null); }} size="md">
          <Modal.Header>Reset two-factor</Modal.Header>
          <Modal.Body>
            <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); submitReset(); }}>
              {resetError && <Alert color="failure">{resetError}</Alert>}
              {reset && (
                <>
                  <p className="text-gray-700 dark:text-gray-300">
                    Remove two-factor from <strong>{reset.action.email}</strong>, e.g. after they lost their phone.
                    Enter <em>your own</em> code to confirm.
                  </p>
                  <CodeInput id="totp-reset-code" value={resetCode} onChange={setResetCode} allowRecovery autoFocus />
                  <Button type="submit" color="failure" isProcessing={resetting}
                          disabled={resetting || resetCode.trim().length < 6}>
                    Reset two-factor
                  </Button>
                </>
              )}
            </form>
          </Modal.Body>
        </Modal>

        {/* Delete Confirmation Modal */}
        <Modal show={showDeleteConfirm} onClose={closeDeleteConfirm}>
          <Modal.Header>Confirm Delete</Modal.Header>
          <Modal.Body>
            {deleteStep === 1 && userToDelete && (
              <p className="text-gray-700 dark:text-gray-300">
                Are you sure you want to delete user <strong>{userToDelete.email}</strong>?
                This will remove all their network permissions.
              </p>
            )}
            {deleteStep === 2 && userToDelete && (
              <div className="space-y-4">
                <p className="text-gray-700 dark:text-gray-300">
                  To confirm, type the user&apos;s email: <strong>{userToDelete.email}</strong>
                </p>
                <TextInput
                  type="text"
                  value={typedEmail}
                  onChange={(e) => setTypedEmail(e.target.value)}
                  placeholder={userToDelete.email}
                />
                {deleteError && (
                  <p className="text-sm text-red-600 dark:text-red-400">{deleteError}</p>
                )}
              </div>
            )}
          </Modal.Body>
          <Modal.Footer>
            {deleteStep === 1 ? (
              <>
                <Button color="failure" onClick={() => setDeleteStep(2)}>
                  Continue
                </Button>
                <Button color="gray" onClick={closeDeleteConfirm}>
                  Cancel
                </Button>
              </>
            ) : (
              <>
                <Button
                  color="failure"
                  onClick={handleDeleteUser}
                  disabled={
                    (userToDelete?.email || '').trim() !== typedEmail.trim() || deleting
                  }
                  isProcessing={deleting}
                >
                  Delete
                </Button>
                <Button color="gray" onClick={() => setDeleteStep(1)}>
                  Back
                </Button>
              </>
            )}
          </Modal.Footer>
        </Modal>
      </div>
    </RequireSystemAdmin>
  );
};
