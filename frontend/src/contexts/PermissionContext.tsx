import React, { createContext, useContext, useState, useEffect, useCallback, ReactNode } from 'react';
import { apiClient } from '../api/client';
import { useAuth } from './AuthContext';

interface NetworkPermission {
  network_id: number;
  role: string;
  can_manage_nodes: boolean;
  can_invite_users: boolean;
  can_manage_firewall: boolean;
}

interface PermissionContextType {
  networkPermissions: NetworkPermission[];
  loading: boolean;
  isSystemAdmin: boolean;
  isNetworkOwner: boolean;
  hasNetworkPermission: (networkId: number, permission: string) => boolean;
  hasSystemRole: (role: string) => boolean;
  refreshPermissions: () => Promise<void>;
}

const PermissionContext = createContext<PermissionContextType | undefined>(undefined);

// eslint-disable-next-line react-refresh/only-export-components
export const usePermissions = () => {
  const context = useContext(PermissionContext);
  if (!context) {
    throw new Error('usePermissions must be used within a PermissionProvider');
  }
  return context;
};

interface PermissionProviderProps {
  children: ReactNode;
}

export const PermissionProvider: React.FC<PermissionProviderProps> = ({ children }) => {
  const { user, isAuthenticated } = useAuth();
  const [networkPermissions, setNetworkPermissions] = useState<NetworkPermission[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchPermissions = useCallback(async () => {
    if (!isAuthenticated || !user) {
      setNetworkPermissions([]);
      setLoading(false);
      return;
    }

    try {
      setLoading(true);
      // Fetch user's network permissions
      const response = await apiClient.get('/networks');
      
      // Extract permissions from networks the user has access to
      const permissions: NetworkPermission[] = [];
      
      // Permissions come from list networks (each network includes role and flags for current user)
      if (Array.isArray(response.data)) {
        response.data.forEach((network: { id: number; role?: string; can_manage_nodes?: boolean; can_invite_users?: boolean; can_manage_firewall?: boolean }) => {
          permissions.push({
            network_id: network.id,
            role: network.role ?? 'member',
            can_manage_nodes: network.can_manage_nodes ?? false,
            can_invite_users: network.can_invite_users ?? false,
            can_manage_firewall: network.can_manage_firewall ?? false,
          });
        });
      }
      
      setNetworkPermissions(permissions);
    } catch (error) {
      console.error('Failed to fetch permissions:', error);
      setNetworkPermissions([]);
    } finally {
      setLoading(false);
    }
  }, [isAuthenticated, user]);

  useEffect(() => {
    fetchPermissions();
  }, [fetchPermissions]);

  const isSystemAdmin = user?.system_role === 'system-admin';
  const isNetworkOwner = networkPermissions.some(p => p.role === 'owner');

  const hasNetworkPermission = (networkId: number, permission: string): boolean => {
    if (!user) return false;
    if (isSystemAdmin) return true;

    const perm = networkPermissions.find(p => p.network_id === networkId);
    if (!perm) return false;

    switch (permission) {
      case 'owner':
        return perm.role === 'owner';
      case 'can_manage_nodes':
        return perm.can_manage_nodes || perm.role === 'owner';
      case 'can_invite_users':
        return perm.can_invite_users || perm.role === 'owner';
      case 'can_manage_firewall':
        return perm.can_manage_firewall || perm.role === 'owner';
      default:
        return false;
    }
  };

  const hasSystemRole = (role: string): boolean => {
    if (!user) return false;
    return user.system_role === role;
  };

  const value: PermissionContextType = {
    networkPermissions,
    loading,
    isSystemAdmin,
    isNetworkOwner,
    hasNetworkPermission,
    hasSystemRole,
    refreshPermissions: fetchPermissions,
  };

  return <PermissionContext.Provider value={value}>{children}</PermissionContext.Provider>;
};
