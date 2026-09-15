import React, { useState, useEffect, useCallback } from 'react';
import { useParams, useNavigate, Link } from 'react-router-dom';
import { Card, Table, Badge, Button, Modal, Label, Select, Checkbox, TextInput } from 'flowbite-react';
import { HiArrowLeft, HiPlus, HiPencil, HiTrash, HiGlobe, HiChevronDown, HiChevronRight } from 'react-icons/hi';
import { RequireNetworkOwner } from '../components/permissions/RequireNetworkOwner';
import { apiClient, listNodes } from '../api/client';
import { isNodeActive } from '../utils/nodeStatus';
import type { Node } from '../types/nodes';
import { GroupAccessDiagram } from '../components/GroupAccessDiagram';
import { startReauthFlow } from './ReauthComplete';

interface NetworkInfo {
  id: number;
  name: string;
  subnet_cidr: string;
  cert_curve: "25519" | "P256";
  created_at: string;
  group_count: number;
}

interface NetworkUser {
  user_id: number;
  email: string;
  role: string;
  can_manage_nodes: boolean;
  can_invite_users: boolean;
  can_manage_firewall: boolean;
  invited_by_email: string;
  created_at: string;
}

interface User {
  id: number;
  email: string;
}

export const NetworkDetail: React.FC = () => {
  const { networkId } = useParams<{ networkId: string }>();
  const navigate = useNavigate();
  const [network, setNetwork] = useState<NetworkInfo | null>(null);
  const [users, setUsers] = useState<NetworkUser[]>([]);
  const [allUsers, setAllUsers] = useState<User[]>([]);
  const [nodes, setNodes] = useState<Node[]>([]);
  const [loading, setLoading] = useState(true);
  const [showAddModal, setShowAddModal] = useState(false);
  const [showEditModal, setShowEditModal] = useState(false);
  const [selectedUser, setSelectedUser] = useState<NetworkUser | null>(null);
  const [usersExpanded, setUsersExpanded] = useState(false);

  // Add user form
  const [selectedUserId, setSelectedUserId] = useState<number | ''>('');
  const [addRole, setAddRole] = useState('member');
  const [addCanManageNodes, setAddCanManageNodes] = useState(false);
  const [addCanInviteUsers, setAddCanInviteUsers] = useState(false);
  const [addCanManageFirewall, setAddCanManageFirewall] = useState(false);

  // Edit form
  const [editRole, setEditRole] = useState('member');
  const [editCanManageNodes, setEditCanManageNodes] = useState(false);
  const [editCanInviteUsers, setEditCanInviteUsers] = useState(false);
  const [editCanManageFirewall, setEditCanManageFirewall] = useState(false);

  // Delete network
  const [deleteModal, setDeleteModal] = useState<{
    open: boolean;
    typedName: string;
    redirecting: boolean;
  }>({ open: false, typedName: "", redirecting: false });
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    if (!networkId) return;
    try {
      setLoading(true);
      const [usersRes, allUsersRes, networkRes, nodesRes] = await Promise.all([
        apiClient.get(`/networks/${networkId}/users`),
        apiClient.get('/users'),
        apiClient.get(`/networks/${networkId}`),
        listNodes(Number(networkId)),
      ]);
      setUsers(usersRes.data);
      setAllUsers(allUsersRes.data);
      setNetwork(networkRes.data);
      setNodes(nodesRes);
    } catch (error) {
      console.error('Failed to fetch data:', error);
    } finally {
      setLoading(false);
    }
  }, [networkId]);

  useEffect(() => {
    if (networkId) {
      fetchData();
    }
  }, [networkId, fetchData]);

  const handleAddUser = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!selectedUserId) {
      alert('Please select a user');
      return;
    }

    try {
      await apiClient.post(`/networks/${networkId}/users`, {
        user_id: selectedUserId,
        role: addRole,
        can_manage_nodes: addCanManageNodes,
        can_invite_users: addCanInviteUsers,
        can_manage_firewall: addCanManageFirewall,
      });

      setShowAddModal(false);
      setSelectedUserId('');
      setAddRole('member');
      setAddCanManageNodes(false);
      setAddCanInviteUsers(false);
      setAddCanManageFirewall(false);
      fetchData();
    } catch (error: any) {
      console.error('Failed to add user:', error);
      alert(error.response?.data?.detail || 'Failed to add user');
    }
  };

  const handleEditUser = (user: NetworkUser) => {
    setSelectedUser(user);
    setEditRole(user.role);
    setEditCanManageNodes(user.can_manage_nodes);
    setEditCanInviteUsers(user.can_invite_users);
    setEditCanManageFirewall(user.can_manage_firewall);
    setShowEditModal(true);
  };

  const handleSaveEdit = async () => {
    if (!selectedUser) return;

    try {
      await apiClient.patch(`/networks/${networkId}/users/${selectedUser.user_id}`, {
        role: editRole,
        can_manage_nodes: editCanManageNodes,
        can_invite_users: editCanInviteUsers,
        can_manage_firewall: editCanManageFirewall,
      });

      setShowEditModal(false);
      setSelectedUser(null);
      fetchData();
    } catch (error: any) {
      console.error('Failed to update user:', error);
      alert(error.response?.data?.detail || 'Failed to update user');
    }
  };

  const handleRemoveUser = async (userId: number, email: string) => {
    if (!confirm(`Are you sure you want to remove ${email} from this network?`)) {
      return;
    }

    try {
      await apiClient.delete(`/networks/${networkId}/users/${userId}`);
      fetchData();
    } catch (error: any) {
      console.error('Failed to remove user:', error);
      alert(error.response?.data?.detail || 'Failed to remove user');
    }
  };

  const startDeleteNetwork = async () => {
    if (!network || deleteModal.typedName.trim() !== network.name.trim()) return;
    setDeleteError(null);
    setDeleteModal((m) => ({ ...m, redirecting: true }));
    try {
      await startReauthFlow({ kind: "network-delete", networkId: network.id, networkName: network.name });
    } catch (e) {
      setDeleteError(e instanceof Error ? e.message : "Failed to start reauthentication");
      setDeleteModal((m) => ({ ...m, redirecting: false }));
    }
  };

  // Filter out users who are already members
  const availableUsers = allUsers.filter(
    (user) => !users.some((nu) => nu.user_id === user.id)
  );

  const ownerCount = users.filter((u) => u.role === 'owner').length;
  const memberCount = users.length - ownerCount;
  const activeNodeCount = nodes.filter(isNodeActive).length;

  return (
    <RequireNetworkOwner networkId={networkId ? Number(networkId) : undefined}>
      <div>
        <div className="mb-6 flex items-start justify-between gap-4">
          <div>
            <Button
              color="gray"
              size="sm"
              onClick={() => navigate('/networks')}
              className="mb-4"
            >
              <HiArrowLeft className="mr-2 h-4 w-4" />
              Back to Networks
            </Button>
            <h1 className="text-3xl font-bold">{network?.name || 'Network'}</h1>
            {network && (
              <p className="mt-2 text-gray-600 dark:text-gray-400">
                Subnet: <strong>{network.subnet_cidr}</strong> &middot; Curve:{' '}
                <strong>{network.cert_curve === 'P256' ? 'P256' : 'Curve25519'}</strong> &middot; Created{' '}
                {new Date(network.created_at).toLocaleDateString()}
              </p>
            )}
          </div>
          <Button color="failure" size="sm" onClick={() => setDeleteModal({ open: true, typedName: "", redirecting: false })}>
            <HiTrash className="mr-2 h-4 w-4" />
            Delete Network
          </Button>
        </div>

        <div className="mb-6 flex flex-wrap gap-4 text-sm">
          <Link to={`/dns?network=${networkId}`} className="flex items-center gap-1 text-purple-600 hover:underline dark:text-purple-400">
            <HiGlobe className="h-4 w-4" />
            Manage DNS
          </Link>
        </div>

        {loading ? (
          <Card>
            <p className="text-gray-600 dark:text-gray-400">Loading...</p>
          </Card>
        ) : (
          <>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 max-w-2xl mb-6">
              <button
                type="button"
                onClick={() => setUsersExpanded((v) => !v)}
                className="aspect-square rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-4 text-left shadow-sm hover:shadow-md transition-shadow flex flex-col"
              >
                <div className="flex items-center justify-between">
                  <p className="font-semibold text-gray-900 dark:text-white">Users</p>
                  {usersExpanded ? (
                    <HiChevronDown className="w-4 h-4 text-gray-400" />
                  ) : (
                    <HiChevronRight className="w-4 h-4 text-gray-400" />
                  )}
                </div>
                <div className="mt-auto grid grid-cols-2 gap-3 text-sm">
                  <div>
                    <div className="text-xs text-gray-500 dark:text-gray-400">Owners</div>
                    <div className="font-semibold text-2xl text-gray-900 dark:text-white">{ownerCount}</div>
                  </div>
                  <div>
                    <div className="text-xs text-gray-500 dark:text-gray-400">Members</div>
                    <div className="font-semibold text-2xl text-gray-900 dark:text-white">{memberCount}</div>
                  </div>
                </div>
              </button>

              <button
                type="button"
                onClick={() => navigate(`/nodes?network=${networkId}`)}
                className="aspect-square rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-4 text-left shadow-sm hover:shadow-md transition-shadow flex flex-col"
              >
                <p className="font-semibold text-gray-900 dark:text-white">Nodes</p>
                <div className="mt-auto">
                  <div className="text-xs text-gray-500 dark:text-gray-400">Active / Total</div>
                  <div className="font-semibold text-2xl text-gray-900 dark:text-white">
                    {activeNodeCount}/{nodes.length}
                  </div>
                </div>
              </button>

              <button
                type="button"
                onClick={() => navigate(`/groups?network=${networkId}`)}
                className="aspect-square rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-4 text-left shadow-sm hover:shadow-md transition-shadow flex flex-col"
              >
                <p className="font-semibold text-gray-900 dark:text-white">Groups</p>
                <div className="mt-auto">
                  <div className="text-xs text-gray-500 dark:text-gray-400">Total</div>
                  <div className="font-semibold text-2xl text-gray-900 dark:text-white">
                    {network?.group_count ?? 0}
                  </div>
                </div>
              </button>
            </div>

            {usersExpanded && (
              <div className="mb-6">
                <div className="mb-4 flex items-center justify-between">
                  <h2 className="text-xl font-semibold">Users</h2>
                  <Button color="purple" onClick={() => setShowAddModal(true)}>
                    <HiPlus className="mr-2 h-5 w-5" />
                    Add Existing User
                  </Button>
                </div>
                <Card>
                  <div className="overflow-x-auto">
                    <Table>
                      <Table.Head>
                        <Table.HeadCell>Email</Table.HeadCell>
                        <Table.HeadCell>Role</Table.HeadCell>
                        <Table.HeadCell>Permissions</Table.HeadCell>
                        <Table.HeadCell>Invited By</Table.HeadCell>
                        <Table.HeadCell>
                          <span className="sr-only">Actions</span>
                        </Table.HeadCell>
                      </Table.Head>
                      <Table.Body className="divide-y">
                        {users.map((user) => (
                          <Table.Row key={user.user_id} className="bg-white dark:border-gray-700 dark:bg-gray-800">
                            <Table.Cell className="whitespace-nowrap font-medium text-gray-900 dark:text-white">
                              {user.email}
                            </Table.Cell>
                            <Table.Cell>
                              <Badge color="info" size="sm">{user.role}</Badge>
                            </Table.Cell>
                            <Table.Cell>
                              <div className="flex flex-wrap gap-1">
                                {user.can_manage_nodes && (
                                  <Badge color="success" size="sm">Nodes</Badge>
                                )}
                                {user.can_invite_users && (
                                  <Badge color="info" size="sm">Invite</Badge>
                                )}
                                {user.can_manage_firewall && (
                                  <Badge color="purple" size="sm">Firewall</Badge>
                                )}
                              </div>
                            </Table.Cell>
                            <Table.Cell className="text-sm text-gray-500 dark:text-gray-400">
                              {user.invited_by_email || 'N/A'}
                            </Table.Cell>
                            <Table.Cell>
                              <div className="flex gap-2">
                                <Button
                                  size="xs"
                                  color="purple"
                                  onClick={() => handleEditUser(user)}
                                >
                                  <HiPencil className="mr-1 h-4 w-4" />
                                  Edit
                                </Button>
                                <Button
                                  size="xs"
                                  color="failure"
                                  onClick={() => handleRemoveUser(user.user_id, user.email)}
                                >
                                  <HiTrash className="mr-1 h-4 w-4" />
                                  Remove
                                </Button>
                              </div>
                            </Table.Cell>
                          </Table.Row>
                        ))}
                      </Table.Body>
                    </Table>
                    {users.length === 0 && (
                      <div className="p-8 text-center">
                        <p className="text-gray-500 dark:text-gray-400">No users in this network yet.</p>
                      </div>
                    )}
                  </div>
                </Card>
              </div>
            )}

            <div>
              <h2 className="text-xl font-semibold mb-4">Group Access</h2>
              {networkId && <GroupAccessDiagram networkId={Number(networkId)} nodes={nodes} />}
            </div>
          </>
        )}

        {/* Add User Modal */}
        <Modal show={showAddModal} onClose={() => setShowAddModal(false)}>
          <Modal.Header>Add User to Network</Modal.Header>
          <Modal.Body>
            <form onSubmit={handleAddUser} className="space-y-4">
              <div>
                <Label htmlFor="user" value="User" />
                <Select
                  id="user"
                  value={selectedUserId}
                  onChange={(e) => setSelectedUserId(Number(e.target.value))}
                  required
                >
                  <option value="">Select a user</option>
                  {availableUsers.map((user) => (
                    <option key={user.id} value={user.id}>
                      {user.email}
                    </option>
                  ))}
                </Select>
              </div>

              <div>
                <Label htmlFor="add-role" value="Role" />
                <Select
                  id="add-role"
                  value={addRole}
                  onChange={(e) => setAddRole(e.target.value)}
                >
                  <option value="member">Member</option>
                  <option value="owner">Owner</option>
                </Select>
              </div>

              <div>
                <Label value="Permissions" />
                <div className="flex flex-col gap-2 mt-2">
                  <div className="flex items-center gap-2">
                    <Checkbox
                      id="add-manage-nodes"
                      checked={addCanManageNodes}
                      onChange={(e) => setAddCanManageNodes(e.target.checked)}
                    />
                    <Label htmlFor="add-manage-nodes">Can manage nodes</Label>
                  </div>
                  <div className="flex items-center gap-2">
                    <Checkbox
                      id="add-invite-users"
                      checked={addCanInviteUsers}
                      onChange={(e) => setAddCanInviteUsers(e.target.checked)}
                    />
                    <Label htmlFor="add-invite-users">Can invite users</Label>
                  </div>
                  <div className="flex items-center gap-2">
                    <Checkbox
                      id="add-manage-firewall"
                      checked={addCanManageFirewall}
                      onChange={(e) => setAddCanManageFirewall(e.target.checked)}
                    />
                    <Label htmlFor="add-manage-firewall">Can manage firewall</Label>
                  </div>
                </div>
              </div>
            </form>
          </Modal.Body>
          <Modal.Footer>
            <Button onClick={handleAddUser}>Add User</Button>
            <Button color="gray" onClick={() => setShowAddModal(false)}>
              Cancel
            </Button>
          </Modal.Footer>
        </Modal>

        {/* Edit User Modal */}
        <Modal show={showEditModal} onClose={() => setShowEditModal(false)}>
          <Modal.Header>Edit User Permissions</Modal.Header>
          <Modal.Body>
            <div className="space-y-4">
              {selectedUser && (
                <div>
                  <Label value="User" />
                  <p className="text-sm text-gray-900 dark:text-white font-medium">{selectedUser.email}</p>
                </div>
              )}

              <div>
                <Label htmlFor="edit-role" value="Role" />
                <Select
                  id="edit-role"
                  value={editRole}
                  onChange={(e) => setEditRole(e.target.value)}
                >
                  <option value="member">Member</option>
                  <option value="owner">Owner</option>
                </Select>
              </div>

              <div>
                <Label value="Permissions" />
                <div className="flex flex-col gap-2 mt-2">
                  <div className="flex items-center gap-2">
                    <Checkbox
                      id="edit-manage-nodes"
                      checked={editCanManageNodes}
                      onChange={(e) => setEditCanManageNodes(e.target.checked)}
                    />
                    <Label htmlFor="edit-manage-nodes">Can manage nodes</Label>
                  </div>
                  <div className="flex items-center gap-2">
                    <Checkbox
                      id="edit-invite-users"
                      checked={editCanInviteUsers}
                      onChange={(e) => setEditCanInviteUsers(e.target.checked)}
                    />
                    <Label htmlFor="edit-invite-users">Can invite users</Label>
                  </div>
                  <div className="flex items-center gap-2">
                    <Checkbox
                      id="edit-manage-firewall"
                      checked={editCanManageFirewall}
                      onChange={(e) => setEditCanManageFirewall(e.target.checked)}
                    />
                    <Label htmlFor="edit-manage-firewall">Can manage firewall</Label>
                  </div>
                </div>
              </div>
            </div>
          </Modal.Body>
          <Modal.Footer>
            <Button onClick={handleSaveEdit}>Save</Button>
            <Button color="gray" onClick={() => setShowEditModal(false)}>
              Cancel
            </Button>
          </Modal.Footer>
        </Modal>

        {/* Delete Network Modal */}
        <Modal
          show={deleteModal.open}
          onClose={() => setDeleteModal({ open: false, typedName: "", redirecting: false })}
          size="md"
          dismissible={!deleteModal.redirecting}
        >
          <Modal.Header>Delete network</Modal.Header>
          <Modal.Body>
            {deleteError && (
              <div className="mb-4 p-3 text-sm text-red-700 bg-red-100 rounded-lg dark:bg-red-200 dark:text-red-800">
                {deleteError}
              </div>
            )}
            {network && (
              <>
                <p className="text-gray-600 dark:text-gray-400 mb-4">
                  Deleting a network removes all nodes, certificates, and settings.
                  This cannot be undone.
                </p>
                <p className="text-gray-600 dark:text-gray-400 mb-2">
                  To confirm, type the network name: <strong>{network.name}</strong>
                </p>
                <TextInput
                  type="text"
                  value={deleteModal.typedName}
                  onChange={(e) => setDeleteModal((m) => ({ ...m, typedName: e.target.value }))}
                  placeholder={network.name}
                  className="mt-2"
                />
              </>
            )}
          </Modal.Body>
          <Modal.Footer>
            <Button
              color="failure"
              onClick={startDeleteNetwork}
              disabled={
                !network ||
                deleteModal.typedName.trim() !== network.name.trim() ||
                deleteModal.redirecting
              }
            >
              {deleteModal.redirecting ? "Redirecting to reauthenticate..." : "Delete network"}
            </Button>
            <Button
              color="gray"
              onClick={() => setDeleteModal({ open: false, typedName: "", redirecting: false })}
              disabled={deleteModal.redirecting}
            >
              Cancel
            </Button>
          </Modal.Footer>
        </Modal>
      </div>
    </RequireNetworkOwner>
  );
};
