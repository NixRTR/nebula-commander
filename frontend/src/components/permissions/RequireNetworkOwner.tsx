import React, { ReactNode } from 'react';
import { usePermissions } from '../../contexts/PermissionContext';

interface RequireNetworkOwnerProps {
  children: ReactNode;
  networkId?: number;
  fallback?: ReactNode;
}

export const RequireNetworkOwner: React.FC<RequireNetworkOwnerProps> = ({ 
  children, 
  networkId,
  fallback 
}) => {
  const { isSystemAdmin, isNetworkOwner, hasNetworkPermission, loading } = usePermissions();

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-purple-600 mx-auto"></div>
          <p className="mt-4 text-gray-600">Loading permissions...</p>
        </div>
      </div>
    );
  }

  // System admins always have access
  if (isSystemAdmin) {
    return <>{children}</>;
  }

  // If networkId is specified, check specific network permission
  if (networkId !== undefined) {
    if (!hasNetworkPermission(networkId, 'owner')) {
      if (fallback) {
        return <>{fallback}</>;
      }
      
      return (
        <div className="flex items-center justify-center min-h-screen">
          <div className="text-center max-w-md">
            <div className="bg-red-100 border border-red-400 text-red-700 px-4 py-3 rounded">
              <h2 className="text-xl font-bold mb-2">Access Denied</h2>
              <p>You need to be a network owner to access this page.</p>
            </div>
          </div>
        </div>
      );
    }
  } else {
    // No specific network, just check if user owns any network
    if (!isNetworkOwner) {
      if (fallback) {
        return <>{fallback}</>;
      }
      
      return (
        <div className="flex items-center justify-center min-h-screen">
          <div className="text-center max-w-md">
            <div className="bg-red-100 border border-red-400 text-red-700 px-4 py-3 rounded">
              <h2 className="text-xl font-bold mb-2">Access Denied</h2>
              <p>You need to be a network owner to access this page.</p>
            </div>
          </div>
        </div>
      );
    }
  }

  return <>{children}</>;
};
