import React, { ReactNode } from 'react';
import { usePermissions } from '../../contexts/PermissionContext';

interface RequireSystemAdminProps {
  children: ReactNode;
  fallback?: ReactNode;
}

export const RequireSystemAdmin: React.FC<RequireSystemAdminProps> = ({ 
  children, 
  fallback 
}) => {
  const { isSystemAdmin, loading } = usePermissions();

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

  if (!isSystemAdmin) {
    if (fallback) {
      return <>{fallback}</>;
    }
    
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="text-center max-w-md">
          <div className="bg-red-100 border border-red-400 text-red-700 px-4 py-3 rounded">
            <h2 className="text-xl font-bold mb-2">Access Denied</h2>
            <p>You need system administrator privileges to access this page.</p>
          </div>
        </div>
      </div>
    );
  }

  return <>{children}</>;
};
