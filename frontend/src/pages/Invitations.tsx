import React, { useState, useEffect } from 'react';
import { Card, Table, Badge, Button, Label, TextInput, Select, Checkbox, Tabs, Alert } from 'flowbite-react';
import { HiClipboard, HiTrash, HiMail } from 'react-icons/hi';
import { RequireNetworkOwner } from '../components/permissions/RequireNetworkOwner';
import { apiClient } from '../api/client';
import { useToast } from '../contexts/ToastContext';

interface Network {
  id: number;
  name: string;
}

interface Invitation {
  id: number;
  email: string;
  network_id: number;
  network_name: string;
  invited_by_email: string;
  token: string;
  role: string;
  can_manage_nodes: boolean;
  can_invite_users: boolean;
  can_manage_firewall: boolean;
  status: string;
  expires_at: string;
  created_at: string;
  email_status: string;
  email_sent_at: string | null;
  email_error: string | null;
}

export const Invitations: React.FC = () => {
  const { showToast, updateToast } = useToast();
  const [invitations, setInvitations] = useState<Invitation[]>([]);
  const [networks, setNetworks] = useState<Network[]>([]);
  const [loading, setLoading] = useState(true);
  
  // Form state
  const [email, setEmail] = useState('');
  const [selectedNetworkId, setSelectedNetworkId] = useState<number | ''>('');
  const [role, setRole] = useState('member');
  const [canManageNodes, setCanManageNodes] = useState(false);
  const [canInviteUsers, setCanInviteUsers] = useState(false);
  const [canManageFirewall, setCanManageFirewall] = useState(false);
  const [expiresInDays, setExpiresInDays] = useState(7);
  const [generatedLink, setGeneratedLink] = useState('');

  useEffect(() => {
    fetchData();
  }, []);

  const fetchData = async () => {
    try {
      setLoading(true);
      const [invitationsRes, networksRes] = await Promise.all([
        apiClient.get('/invitations'),
        apiClient.get('/networks'),
      ]);
      setInvitations(invitationsRes.data);
      setNetworks(networksRes.data);
    } catch (error) {
      console.error('Failed to fetch data:', error);
    } finally {
      setLoading(false);
    }
  };

  const pollEmailStatus = async (invitationId: number, toastId: string) => {
    const maxAttempts = 10;
    let attempts = 0;
    
    const poll = async () => {
      if (attempts >= maxAttempts) {
        updateToast(toastId, {
          type: 'warning',
          title: 'Email status unknown',
          message: 'Check the invitations list for status',
          duration: 5000,
        });
        return;
      }
      
      attempts++;
      
      try {
        const response = await apiClient.get('/invitations');
        const invitation = response.data.find((inv: Invitation) => inv.id === invitationId);
        
        if (invitation) {
          if (invitation.email_status === 'sent') {
            updateToast(toastId, {
              type: 'success',
              title: 'Email sent!',
              message: `Invitation email sent to ${invitation.email}`,
              duration: 5000,
            });
            fetchData();
            return;
          } else if (invitation.email_status === 'failed') {
            updateToast(toastId, {
              type: 'error',
              title: 'Email failed',
              message: invitation.email_error || 'Failed to send email',
              duration: 7000,
            });
            fetchData();
            return;
          } else if (invitation.email_status === 'sending') {
            // Still sending, poll again
            setTimeout(poll, 1000);
          }
        }
      } catch (error) {
        console.error('Failed to poll email status:', error);
      }
    };
    
    setTimeout(poll, 1000);
  };

  const handleSendInvitation = async (e: React.FormEvent) => {
    e.preventDefault();
    
    if (!selectedNetworkId) {
      showToast('error', 'Error', 'Please select a network');
      return;
    }

    const toastId = showToast('loading', 'Sending invitation...', 'Creating invitation and sending email');

    try {
      const response = await apiClient.post('/invitations', {
        email,
        network_id: selectedNetworkId,
        role,
        can_manage_nodes: canManageNodes,
        can_invite_users: canInviteUsers,
        can_manage_firewall: canManageFirewall,
        expires_in_days: expiresInDays,
      });

      const invitationToken = response.data.token;
      const link = `${window.location.origin}/invitations/accept/${invitationToken}`;
      setGeneratedLink(link);
      
      // Reset form
      setEmail('');
      setRole('member');
      setCanManageNodes(false);
      setCanInviteUsers(false);
      setCanManageFirewall(false);
      setExpiresInDays(7);
      
      // Check email status
      const emailStatus = response.data.email_status;
      if (emailStatus === 'not_sent') {
        updateToast(toastId, {
          type: 'warning',
          title: 'Invitation created',
          message: 'Email not sent (SMTP disabled). Copy the link below.',
          duration: 5000,
        });
      } else if (emailStatus === 'sending') {
        // Poll for status update
        pollEmailStatus(response.data.id, toastId);
      } else if (emailStatus === 'sent') {
        updateToast(toastId, {
          type: 'success',
          title: 'Invitation sent!',
          message: `Email sent to ${response.data.email}`,
          duration: 5000,
        });
      } else if (emailStatus === 'failed') {
        updateToast(toastId, {
          type: 'error',
          title: 'Email failed',
          message: 'Invitation created but email failed to send. Use the link below or resend.',
          duration: 7000,
        });
      }
      
      // Refresh invitations list
      fetchData();
    } catch (error: any) {
      console.error('Failed to send invitation:', error);
      updateToast(toastId, {
        type: 'error',
        title: 'Failed to send invitation',
        message: error.response?.data?.detail || 'An error occurred',
        duration: 5000,
      });
    }
  };

  const handleResendEmail = async (invitationId: number) => {
    const toastId = showToast('loading', 'Resending email...', 'Please wait');
    
    try {
      const response = await apiClient.post(`/invitations/${invitationId}/resend`);
      
      if (response.data.email_status === 'sending') {
        pollEmailStatus(invitationId, toastId);
      } else if (response.data.email_status === 'sent') {
        updateToast(toastId, {
          type: 'success',
          title: 'Email sent!',
          message: 'Invitation email resent successfully',
          duration: 5000,
        });
      }
      
      fetchData();
    } catch (error: any) {
      updateToast(toastId, {
        type: 'error',
        title: 'Failed to resend',
        message: error.response?.data?.detail || 'An error occurred',
        duration: 5000,
      });
    }
  };

  const handleRevokeInvitation = async (invitationId: number) => {
    if (!confirm('Are you sure you want to revoke this invitation?')) {
      return;
    }

    try {
      await apiClient.delete(`/invitations/${invitationId}`);
      fetchData();
    } catch (error) {
      console.error('Failed to revoke invitation:', error);
      alert('Failed to revoke invitation');
    }
  };

  const copyToClipboard = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      showToast('success', 'Copied!', 'Link copied to clipboard');
    } catch (error) {
      // Fallback for browsers that don't support clipboard API
      const textArea = document.createElement('textarea');
      textArea.value = text;
      textArea.style.position = 'fixed';
      textArea.style.left = '-999999px';
      document.body.appendChild(textArea);
      textArea.select();
      try {
        document.execCommand('copy');
        showToast('success', 'Copied!', 'Link copied to clipboard');
      } catch (err) {
        showToast('error', 'Copy failed', 'Please copy the link manually');
      }
      document.body.removeChild(textArea);
    }
  };

  const getStatusBadgeColor = (status: string) => {
    switch (status) {
      case 'pending':
        return 'warning';
      case 'accepted':
        return 'success';
      case 'expired':
        return 'gray';
      case 'revoked':
        return 'failure';
      default:
        return 'gray';
    }
  };

  return (
    <RequireNetworkOwner>
      <div>
        <div className="mb-6">
          <h1 className="text-3xl font-bold">Invitations</h1>
          <p className="mt-2 text-gray-600 dark:text-gray-400">Invite users to join your networks</p>
        </div>

        <Tabs aria-label="Invitation tabs">
          <Tabs.Item active title="Pending Invitations" icon={HiMail}>
            {loading ? (
              <Card>
                <p className="text-gray-600 dark:text-gray-400">Loading invitations...</p>
              </Card>
            ) : invitations.length === 0 ? (
              <Card>
                <p className="text-center text-gray-500 dark:text-gray-400">No invitations found</p>
              </Card>
            ) : (
              <Card>
                <div className="overflow-x-auto">
                  <Table>
                    <Table.Head>
                      <Table.HeadCell>Email</Table.HeadCell>
                      <Table.HeadCell>Network</Table.HeadCell>
                      <Table.HeadCell>Role</Table.HeadCell>
                      <Table.HeadCell>Status</Table.HeadCell>
                      <Table.HeadCell>Expires</Table.HeadCell>
                      <Table.HeadCell>
                        <span className="sr-only">Actions</span>
                      </Table.HeadCell>
                    </Table.Head>
                    <Table.Body className="divide-y">
                      {invitations.map((invitation) => (
                        <Table.Row key={invitation.id} className="bg-white dark:border-gray-700 dark:bg-gray-800">
                          <Table.Cell className="whitespace-nowrap font-medium text-gray-900 dark:text-white">
                            {invitation.email}
                          </Table.Cell>
                          <Table.Cell>{invitation.network_name}</Table.Cell>
                          <Table.Cell>
                            <Badge color="info" size="sm">{invitation.role}</Badge>
                          </Table.Cell>
                          <Table.Cell>
                            <div className="flex flex-col gap-1">
                              <Badge color={getStatusBadgeColor(invitation.status)}>
                                {invitation.status}
                              </Badge>
                              {invitation.email_status === 'sent' && (
                                <Badge color="success" size="xs">
                                  Email sent
                                </Badge>
                              )}
                              {invitation.email_status === 'sending' && (
                                <Badge color="info" size="xs">
                                  Sending...
                                </Badge>
                              )}
                              {invitation.email_status === 'failed' && (
                                <Badge color="failure" size="xs" title={invitation.email_error || undefined}>
                                  Email failed
                                </Badge>
                              )}
                              {invitation.email_status === 'not_sent' && (
                                <Badge color="gray" size="xs">
                                  Not emailed
                                </Badge>
                              )}
                            </div>
                          </Table.Cell>
                          <Table.Cell>{new Date(invitation.expires_at).toLocaleDateString()}</Table.Cell>
                          <Table.Cell>
                            {invitation.status === 'pending' && (
                              <div className="flex gap-2">
                                <Button
                                  size="xs"
                                  color="gray"
                                  onClick={() => copyToClipboard(`${window.location.origin}/invitations/accept/${invitation.token}`)}
                                >
                                  <HiClipboard className="mr-1 h-4 w-4" />
                                  Copy Link
                                </Button>
                                {(invitation.email_status === 'failed' || invitation.email_status === 'not_sent') && (
                                  <Button
                                    size="xs"
                                    color="purple"
                                    onClick={() => handleResendEmail(invitation.id)}
                                  >
                                    <HiMail className="mr-1 h-4 w-4" />
                                    Resend
                                  </Button>
                                )}
                                <Button
                                  size="xs"
                                  color="failure"
                                  onClick={() => handleRevokeInvitation(invitation.id)}
                                >
                                  <HiTrash className="mr-1 h-4 w-4" />
                                  Revoke
                                </Button>
                              </div>
                            )}
                          </Table.Cell>
                        </Table.Row>
                      ))}
                    </Table.Body>
                  </Table>
                </div>
              </Card>
            )}
          </Tabs.Item>

          <Tabs.Item title="Send Invitation" icon={HiMail}>
            <Card>
              <form onSubmit={handleSendInvitation} className="space-y-4">
                <div>
                  <Label htmlFor="email" value="Email Address" />
                  <TextInput
                    id="email"
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="user@example.com"
                    required
                  />
                </div>

                <div>
                  <Label htmlFor="network" value="Network" />
                  <Select
                    id="network"
                    value={selectedNetworkId}
                    onChange={(e) => setSelectedNetworkId(Number(e.target.value))}
                    required
                  >
                    <option value="">Select a network</option>
                    {networks.map((network) => (
                      <option key={network.id} value={network.id}>
                        {network.name}
                      </option>
                    ))}
                  </Select>
                </div>

                <div>
                  <Label htmlFor="role" value="Role" />
                  <Select
                    id="role"
                    value={role}
                    onChange={(e) => setRole(e.target.value)}
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
                        id="manage-nodes"
                        checked={canManageNodes}
                        onChange={(e) => setCanManageNodes(e.target.checked)}
                      />
                      <Label htmlFor="manage-nodes">Can manage nodes</Label>
                    </div>
                    <div className="flex items-center gap-2">
                      <Checkbox
                        id="invite-users"
                        checked={canInviteUsers}
                        onChange={(e) => setCanInviteUsers(e.target.checked)}
                      />
                      <Label htmlFor="invite-users">Can invite users</Label>
                    </div>
                    <div className="flex items-center gap-2">
                      <Checkbox
                        id="manage-firewall"
                        checked={canManageFirewall}
                        onChange={(e) => setCanManageFirewall(e.target.checked)}
                      />
                      <Label htmlFor="manage-firewall">Can manage firewall</Label>
                    </div>
                  </div>
                </div>

                <div>
                  <Label htmlFor="expires" value="Expires in (days)" />
                  <TextInput
                    id="expires"
                    type="number"
                    value={expiresInDays}
                    onChange={(e) => setExpiresInDays(Number(e.target.value))}
                    min="1"
                    max="365"
                  />
                </div>

                <Button type="submit" color="purple">
                  Send Invitation
                </Button>
              </form>

              {generatedLink && (
                <Alert color="success" className="mt-4">
                  <div className="space-y-2">
                    <h3 className="font-medium">Invitation Created!</h3>
                    <p className="text-sm">Share this link with the user:</p>
                    <div className="flex items-center gap-2">
                      <TextInput
                        value={generatedLink}
                        readOnly
                        className="flex-1"
                      />
                      <Button
                        size="sm"
                        color="success"
                        onClick={() => copyToClipboard(generatedLink)}
                      >
                        <HiClipboard className="mr-1 h-4 w-4" />
                        Copy
                      </Button>
                    </div>
                  </div>
                </Alert>
              )}
            </Card>
          </Tabs.Item>
        </Tabs>
      </div>
    </RequireNetworkOwner>
  );
};
