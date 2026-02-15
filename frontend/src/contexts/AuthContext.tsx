import React, { createContext, useContext, useState, useEffect, ReactNode } from 'react';
import { apiClient } from '../api/client';

interface User {
  sub: string;
  email?: string;
  name?: string;
  role: string;
  system_role: string;
}

interface AuthContextType {
  user: User | null;
  loading: boolean;
  isAuthenticated: boolean;
  login: () => void;
  logout: () => void;
  setToken: (token: string) => void;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};

interface AuthProviderProps {
  children: ReactNode;
}

export const AuthProvider: React.FC<AuthProviderProps> = ({ children }) => {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  // Check authentication status on mount
  useEffect(() => {
    checkAuth();
  }, []);

  const checkAuth = async () => {
    try {
      const token = localStorage.getItem('token');
      console.log('Checking auth, token exists:', !!token);
      const response = await apiClient.get('/auth/me');
      console.log('Auth response:', response.data);
      if (response.data.authenticated) {
        setUser({
          sub: response.data.sub,
          email: response.data.email,
          name: response.data.name,
          role: response.data.role,
          system_role: response.data.system_role || response.data.role || 'user',
        });
      } else {
        setUser(null);
      }
    } catch (error) {
      console.error('Auth check failed:', error);
      setUser(null);
    } finally {
      setLoading(false);
    }
  };

  const login = () => {
    // Redirect to backend OAuth login endpoint
    window.location.href = '/api/auth/login';
  };

  const logout = async () => {
    try {
      // Clear local token
      localStorage.removeItem('token');
      setUser(null);
      
      // Redirect to backend logout endpoint (which redirects to Keycloak)
      window.location.href = '/api/auth/logout';
    } catch (error) {
      console.error('Logout failed:', error);
    }
  };

  const setToken = (token: string) => {
    // Store token and re-check auth
    console.log('Setting token:', token.substring(0, 20) + '...');
    localStorage.setItem('token', token);
    // Small delay to ensure localStorage is updated before checking auth
    setTimeout(() => {
      checkAuth();
    }, 100);
  };

  const value: AuthContextType = {
    user,
    loading,
    isAuthenticated: !!user,
    login,
    logout,
    setToken,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};
