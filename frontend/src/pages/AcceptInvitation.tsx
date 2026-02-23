import React, { useState, useEffect, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Card, Badge, Button, Spinner } from 'flowbite-react';
import { HiCheckCircle, HiXCircle } from 'react-icons/hi';
import { apiClient } from '../api/client';
import { useAuth } from '../contexts/AuthContext';

interface InvitationDetails {
  email: string;
  network_name: string;
  invited_by_email: string;
  role: string;
  can_manage_nodes: boolean;
  can_invite_users: boolean;
  can_manage_firewall: boolean;
  status: string;
  expires_at: string;
}

export const AcceptInvitation: React.FC = () => {
  const { token } = useParams<{ token: string }>();
  const navigate = useNavigate();
  const { isAuthenticated, login } = useAuth();
  const [invitation, setInvitation] = useState<InvitationDetails | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [accepting, setAccepting] = useState(false);
  const [accepted, setAccepted] = useState(false);

  const fetchInvitation = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const response = await apiClient.get(`/invitations/public/${token}`);
      setInvitation(response.data);
    } catch (error: any) {
      console.error('Failed to fetch invitation:', error);
      if (error.response?.status === 404) {
        setError('Invitation not found');
      } else if (error.response?.status === 410) {
        setError('This invitation has expired');
      } else if (error.response?.status === 400) {
        setError(error.response.data.detail || 'This invitation is no longer valid');
      } else {
        setError('Failed to load invitation details');
      }
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    fetchInvitation();
  }, [fetchInvitation]);

  const handleAccept = async () => {
    if (!isAuthenticated) {
      // Store the return URL and redirect to login
      localStorage.setItem('invitation_return_url', window.location.pathname);
      login();
      return;
    }

    try {
      setAccepting(true);
      await apiClient.post(`/invitations/${token}/accept`);
      setAccepted(true);
      
      // Redirect to networks page after 2 seconds
      setTimeout(() => {
        navigate('/networks');
      }, 2000);
    } catch (error: any) {
      console.error('Failed to accept invitation:', error);
      alert(error.response?.data?.detail || 'Failed to accept invitation');
    } finally {
      setAccepting(false);
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50 dark:bg-gray-900">
        <Card className="w-full max-w-md">
          <div className="text-center">
            <Spinner size="xl" />
            <p className="mt-4 text-gray-600 dark:text-gray-400">Loading invitation...</p>
          </div>
        </Card>
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50 dark:bg-gray-900 p-4">
        <Card className="w-full max-w-md">
          <div className="text-center">
            <div className="mx-auto flex items-center justify-center h-12 w-12 rounded-full bg-red-100 dark:bg-red-900">
              <HiXCircle className="h-6 w-6 text-red-600 dark:text-red-400" />
            </div>
            <h2 className="mt-4 text-2xl font-bold text-gray-900 dark:text-white">Invalid Invitation</h2>
            <p className="mt-2 text-gray-600 dark:text-gray-400">{error}</p>
            <Button
              color="gray"
              onClick={() => navigate('/')}
              className="mt-6"
            >
              Go to Home
            </Button>
          </div>
        </Card>
      </div>
    );
  }

  if (accepted) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50 dark:bg-gray-900 p-4">
        <Card className="w-full max-w-md">
          <div className="text-center">
            <div className="mx-auto flex items-center justify-center h-12 w-12 rounded-full bg-green-100 dark:bg-green-900">
              <HiCheckCircle className="h-6 w-6 text-green-600 dark:text-green-400" />
            </div>
            <h2 className="mt-4 text-2xl font-bold text-gray-900 dark:text-white">Invitation Accepted!</h2>
            <p className="mt-2 text-gray-600 dark:text-gray-400">
              You now have access to the network. Redirecting...
            </p>
          </div>
        </Card>
      </div>
    );
  }

  if (!invitation) {
    return null;
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50 dark:bg-gray-900 p-4">
      <Card className="w-full max-w-md">
        <div className="text-center mb-6">
          <h2 className="text-3xl font-bold text-gray-900 dark:text-white">Network Invitation</h2>
          <p className="mt-2 text-sm text-gray-600 dark:text-gray-400">
            You've been invited to join a network
          </p>
        </div>

        <div className="space-y-4 mb-6">
          <Card>
            <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-3">Invitation Details</h3>
            <dl className="space-y-3">
              <div>
                <dt className="text-xs text-gray-500 dark:text-gray-400">Network</dt>
                <dd className="text-sm font-medium text-gray-900 dark:text-white">{invitation.network_name}</dd>
              </div>
              <div>
                <dt className="text-xs text-gray-500 dark:text-gray-400">Invited by</dt>
                <dd className="text-sm font-medium text-gray-900 dark:text-white">{invitation.invited_by_email}</dd>
              </div>
              <div>
                <dt className="text-xs text-gray-500 dark:text-gray-400">Role</dt>
                <dd className="text-sm font-medium">
                  <Badge color="info" className="capitalize">{invitation.role}</Badge>
                </dd>
              </div>
              <div>
                <dt className="text-xs text-gray-500 dark:text-gray-400 mb-1">Permissions</dt>
                <dd className="flex flex-wrap gap-1">
                  {invitation.can_manage_nodes && (
                    <Badge color="success" size="sm">Manage Nodes</Badge>
                  )}
                  {invitation.can_invite_users && (
                    <Badge color="info" size="sm">Invite Users</Badge>
                  )}
                  {invitation.can_manage_firewall && (
                    <Badge color="purple" size="sm">Manage Firewall</Badge>
                  )}
                  {!invitation.can_manage_nodes && !invitation.can_invite_users && !invitation.can_manage_firewall && (
                    <span className="text-xs text-gray-500 dark:text-gray-400">No special permissions</span>
                  )}
                </dd>
              </div>
              <div>
                <dt className="text-xs text-gray-500 dark:text-gray-400">Expires</dt>
                <dd className="text-sm font-medium text-gray-900 dark:text-white">
                  {new Date(invitation.expires_at).toLocaleDateString()}
                </dd>
              </div>
            </dl>
          </Card>
        </div>

        <div className="space-y-3">
          {isAuthenticated ? (
            <Button
              color="purple"
              onClick={handleAccept}
              disabled={accepting}
              className="w-full"
            >
              {accepting ? (
                <>
                  <Spinner size="sm" className="mr-2" />
                  Accepting...
                </>
              ) : (
                'Accept Invitation'
              )}
            </Button>
          ) : (
            <>
              <Button
                color="purple"
                onClick={handleAccept}
                className="w-full"
              >
                Login to Accept
              </Button>
              <p className="text-xs text-center text-gray-500 dark:text-gray-400">
                You need to be logged in to accept this invitation
              </p>
            </>
          )}
          
          <Button
            color="gray"
            onClick={() => navigate('/')}
            className="w-full"
          >
            Cancel
          </Button>
        </div>
      </Card>
    </div>
  );
};
