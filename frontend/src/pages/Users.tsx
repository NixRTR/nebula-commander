import React, { useState, useEffect } from 'react';
import { Card, Table, Badge, Button, Modal, Label, Select } from 'flowbite-react';
import { HiEye, HiPencil, HiTrash } from 'react-icons/hi';
import { RequireSystemAdmin } from '../components/permissions/RequireSystemAdmin';
import { apiClient } from '../api/client';

interface User {
  id: number;
  email: string;
  system_role: string;
  network_count: number;
  created_at: string;
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
  const [showEditModal, setShowEditModal] = useState(false);
  const [editingRole, setEditingRole] = useState('');
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [userToDelete, setUserToDelete] = useState<User | null>(null);
  const [showDetailsModal, setShowDetailsModal] = useState(false);

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
      setShowDetailsModal(true);
    } catch (error) {
      console.error('Failed to fetch user details:', error);
    }
  };

  const handleEditRole = (user: User) => {
    setSelectedUser(user as UserDetail);
    setEditingRole(user.system_role);
    setShowEditModal(true);
  };

  const handleSaveRole = async () => {
    if (!selectedUser) return;

    try {
      await apiClient.patch(`/users/${selectedUser.id}`, {
        system_role: editingRole,
      });
      setShowEditModal(false);
      fetchUsers();
    } catch (error) {
      console.error('Failed to update user role:', error);
      alert('Failed to update user role');
    }
  };

  const handleDeleteUser = async () => {
    if (!userToDelete) return;

    try {
      await apiClient.delete(`/users/${userToDelete.id}`);
      setShowDeleteConfirm(false);
      setUserToDelete(null);
      fetchUsers();
    } catch (error) {
      console.error('Failed to delete user:', error);
      alert('Failed to delete user');
    }
  };

  const getRoleBadgeColor = (role: string) => {
    switch (role) {
      case 'system-admin':
        return 'failure';
      case 'network-owner':
        return 'info';
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
        ) : (
          <Card>
            <div className="overflow-x-auto">
              <Table>
                <Table.Head>
                  <Table.HeadCell>Email</Table.HeadCell>
                  <Table.HeadCell>System Role</Table.HeadCell>
                  <Table.HeadCell>Networks</Table.HeadCell>
                  <Table.HeadCell>Created</Table.HeadCell>
                  <Table.HeadCell>
                    <span className="sr-only">Actions</span>
                  </Table.HeadCell>
                </Table.Head>
                <Table.Body className="divide-y">
                  {users.map((user) => (
                    <Table.Row key={user.id} className="bg-white dark:border-gray-700 dark:bg-gray-800">
                      <Table.Cell className="whitespace-nowrap font-medium text-gray-900 dark:text-white">
                        {user.email || 'N/A'}
                      </Table.Cell>
                      <Table.Cell>
                        <Badge color={getRoleBadgeColor(user.system_role)}>
                          {user.system_role}
                        </Badge>
                      </Table.Cell>
                      <Table.Cell>{user.network_count}</Table.Cell>
                      <Table.Cell>{new Date(user.created_at).toLocaleDateString()}</Table.Cell>
                      <Table.Cell>
                        <div className="flex gap-2">
                          <Button
                            size="xs"
                            color="gray"
                            onClick={() => fetchUserDetails(user.id)}
                          >
                            <HiEye className="mr-1 h-4 w-4" />
                            View
                          </Button>
                          <Button
                            size="xs"
                            color="blue"
                            onClick={() => handleEditRole(user)}
                          >
                            <HiPencil className="mr-1 h-4 w-4" />
                            Edit Role
                          </Button>
                          <Button
                            size="xs"
                            color="failure"
                            onClick={() => {
                              setUserToDelete(user);
                              setShowDeleteConfirm(true);
                            }}
                          >
                            <HiTrash className="mr-1 h-4 w-4" />
                            Delete
                          </Button>
                        </div>
                      </Table.Cell>
                    </Table.Row>
                  ))}
                </Table.Body>
              </Table>
              {users.length === 0 && (
                <div className="p-8 text-center">
                  <p className="text-gray-500 dark:text-gray-400">No users found.</p>
                </div>
              )}
            </div>
          </Card>
        )}

        {/* User Details Modal */}
        <Modal show={showDetailsModal && selectedUser !== null} onClose={() => setShowDetailsModal(false)}>
          <Modal.Header>User Details</Modal.Header>
          <Modal.Body>
            {selectedUser && (
              <div className="space-y-4">
                <div>
                  <Label value="Email" />
                  <p className="text-sm text-gray-900 dark:text-white">{selectedUser.email || 'N/A'}</p>
                </div>
                <div>
                  <Label value="System Role" />
                  <p className="text-sm text-gray-900 dark:text-white">{selectedUser.system_role}</p>
                </div>
                <div>
                  <Label value="Created" />
                  <p className="text-sm text-gray-900 dark:text-white">
                    {new Date(selectedUser.created_at).toLocaleString()}
                  </p>
                </div>

                {selectedUser.networks && selectedUser.networks.length > 0 && (
                  <div>
                    <Label value="Network Permissions" />
                    <div className="mt-2 space-y-2">
                      {selectedUser.networks.map((network) => (
                        <Card key={network.id}>
                          <h5 className="text-sm font-bold text-gray-900 dark:text-white">
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
          <Modal.Footer>
            <Button color="gray" onClick={() => setShowDetailsModal(false)}>
              Close
            </Button>
          </Modal.Footer>
        </Modal>

        {/* Edit Role Modal */}
        <Modal show={showEditModal} onClose={() => setShowEditModal(false)}>
          <Modal.Header>Edit User Role</Modal.Header>
          <Modal.Body>
            <div className="space-y-4">
              <div>
                <Label htmlFor="role" value="System Role" />
                <Select
                  id="role"
                  value={editingRole}
                  onChange={(e) => setEditingRole(e.target.value)}
                >
                  <option value="user">User</option>
                  <option value="network-owner">Network Owner</option>
                  <option value="system-admin">System Admin</option>
                </Select>
              </div>
            </div>
          </Modal.Body>
          <Modal.Footer>
            <Button onClick={handleSaveRole}>Save</Button>
            <Button color="gray" onClick={() => setShowEditModal(false)}>
              Cancel
            </Button>
          </Modal.Footer>
        </Modal>

        {/* Delete Confirmation Modal */}
        <Modal show={showDeleteConfirm} onClose={() => setShowDeleteConfirm(false)}>
          <Modal.Header>Confirm Delete</Modal.Header>
          <Modal.Body>
            <p className="text-gray-700 dark:text-gray-300">
              Are you sure you want to delete user <strong>{userToDelete?.email}</strong>? 
              This will remove all their network permissions.
            </p>
          </Modal.Body>
          <Modal.Footer>
            <Button color="failure" onClick={handleDeleteUser}>
              Delete
            </Button>
            <Button color="gray" onClick={() => {
              setShowDeleteConfirm(false);
              setUserToDelete(null);
            }}>
              Cancel
            </Button>
          </Modal.Footer>
        </Modal>
      </div>
    </RequireSystemAdmin>
  );
};
