import React, { ReactNode } from 'react';
import { usePermissions } from '../../contexts/PermissionContext';

interface RequirePermissionProps {
  children: ReactNode;
  networkId: number;
  permission: string;
  fallback?: ReactNode;
}

export const RequirePermission: React.FC<RequirePermissionProps> = ({ 
  children, 
  networkId,
  permission,
  fallback 
}) => {
  const { hasNetworkPermission, loading } = usePermissions();

  if (loading) {
    return (
      <div className="flex items-center justify-center p-4">
        <div className="text-center">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600 mx-auto"></div>
          <p className="mt-2 text-sm text-gray-600">Loading...</p>
        </div>
      </div>
    );
  }

  if (!hasNetworkPermission(networkId, permission)) {
    if (fallback) {
      return <>{fallback}</>;
    }
    
    return null;
  }

  return <>{children}</>;
};
