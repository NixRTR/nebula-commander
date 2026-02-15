import React, { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Card, Table, Badge, Button, Modal, Label, Select, Checkbox } from 'flowbite-react';
import { HiArrowLeft, HiPlus, HiPencil, HiTrash } from 'react-icons/hi';
import { RequireNetworkOwner } from '../components/permissions/RequireNetworkOwner';
import { apiClient } from '../api/client';

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

export const NetworkUsers: React.FC = () => {
  const { networkId } = useParams<{ networkId: string }>();
  const navigate = useNavigate();
  const [users, setUsers] = useState<NetworkUser[]>([]);
  const [allUsers, setAllUsers] = useState<User[]>([]);
  const [loading, setLoading] = useState(true);
  const [showAddModal, setShowAddModal] = useState(false);
  const [showEditModal, setShowEditModal] = useState(false);
  const [selectedUser, setSelectedUser] = useState<NetworkUser | null>(null);
  const [networkName, setNetworkName] = useState('');
  
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

  useEffect(() => {
    if (networkId) {
      fetchData();
    }
  }, [networkId]);

  const fetchData = async () => {
    try {
      setLoading(true);
      const [usersRes, allUsersRes, networkRes] = await Promise.all([
        apiClient.get(`/networks/${networkId}/users`),
        apiClient.get('/users'),
        apiClient.get(`/networks/${networkId}`),
      ]);
      setUsers(usersRes.data);
      setAllUsers(allUsersRes.data);
      setNetworkName(networkRes.data.name);
    } catch (error) {
      console.error('Failed to fetch data:', error);
    } finally {
      setLoading(false);
    }
  };

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

  // Filter out users who are already members
  const availableUsers = allUsers.filter(
    (user) => !users.some((nu) => nu.user_id === user.id)
  );

  return (
    <RequireNetworkOwner networkId={networkId ? Number(networkId) : undefined}>
      <div>
        <div className="mb-6">
          <Button
            color="gray"
            size="sm"
            onClick={() => navigate('/networks')}
            className="mb-4"
          >
            <HiArrowLeft className="mr-2 h-4 w-4" />
            Back to Networks
          </Button>
          <h1 className="text-3xl font-bold">Network Users</h1>
          <p className="mt-2 text-gray-600 dark:text-gray-400">
            Manage users for network: <strong>{networkName}</strong>
          </p>
        </div>

        <div className="mb-4">
          <Button color="blue" onClick={() => setShowAddModal(true)}>
            <HiPlus className="mr-2 h-5 w-5" />
            Add Existing User
          </Button>
        </div>

        {loading ? (
          <Card>
            <p className="text-gray-600 dark:text-gray-400">Loading users...</p>
          </Card>
        ) : (
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
                            color="blue"
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
      </div>
    </RequireNetworkOwner>
  );
};
