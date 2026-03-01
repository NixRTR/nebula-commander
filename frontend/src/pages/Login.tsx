import React, { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { apiClient } from '../api/client';

const Login: React.FC = () => {
  const { login, isAuthenticated } = useAuth();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const error = searchParams.get('error');
  const [oidcStatus, setOidcStatus] = useState<'checking' | 'ready' | 'unavailable'>('checking');
  const [maintenanceMessage, setMaintenanceMessage] = useState<string | null>(null);

  const MAINTENANCE_MESSAGES = [
    "Still Igniting the Cosmic Dust...",
    "Gravity's Just Getting Started...",
    "Interstellar Medium Calibrating...",
    "Condensing Cosmic Dust...",
    "Stellar Nursery Initializing...",
    "Nebular Ignition Pending...",
    "Core Warming Up...",
    "Core heating nicely...",
    "Luminosity Calibration in Progress...",
    "Gravitational forces stabilizing...",
    "Stellar nursery responding...",
    "Ignition Threshold Approaching...",
  ];

  useEffect(() => {
    // If already authenticated, redirect to home
    if (isAuthenticated) {
      navigate('/');
    }
  }, [isAuthenticated, navigate]);

  useEffect(() => {
    const checkOidcStatus = async () => {
      try {
        const response = await apiClient.get<{ status: string }>('/auth/oidc-status');
        if (response.data.status === 'ok' || response.data.status === 'disabled') {
          setOidcStatus('ready');
        } else {
          setOidcStatus('unavailable');
        }
      } catch {
        setOidcStatus('unavailable');
      }
      if (oidcStatus === 'unavailable') {
        const idx = Math.floor(Math.random() * MAINTENANCE_MESSAGES.length);
        setMaintenanceMessage(MAINTENANCE_MESSAGES[idx]);
      }
    };
    checkOidcStatus();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleLogin = () => {
    login();
  };

  return (
    <div
      className="relative min-h-screen flex items-center justify-center bg-gray-900 bg-cover bg-center bg-no-repeat"
      style={{ backgroundImage: 'url(/nebula.webp)' }}
    >
      <div className="absolute inset-0 bg-black/50" aria-hidden="true" />
      <div className="relative z-10 max-w-md w-full space-y-8 p-8 bg-gray-900/90 dark:bg-gray-800/95 rounded-lg shadow-xl border border-purple-800/50 backdrop-blur-sm">
        <div>
          <img src="/logo.svg" alt="Nebula Commander" className="mx-auto h-16 w-auto" />
          <h2 className="mt-6 text-center text-3xl font-extrabold text-white">
            Nebula Commander
          </h2>
          <p className="mt-2 text-center text-sm text-gray-400">
            Sign in to manage your Nebula network
          </p>
        </div>

        {error && (
          <div className="bg-red-900/50 border border-red-700 text-red-200 px-4 py-3 rounded">
            <p className="text-sm">
              {error === 'auth_failed' 
                ? 'Authentication failed. Please try again.' 
                : 'An error occurred during login.'}
            </p>
          </div>
        )}

        {oidcStatus === 'unavailable' ? (
          <div className="text-center bg-purple-900/40 border border-purple-700 px-4 py-6 rounded">
            <p className="text-lg font-semibold text-purple-100">
              {maintenanceMessage ??
                "Nebular Ignition Pending..."}
            </p>
            <p className="mt-2 text-sm text-gray-300">
              Try again in a few moments.
            </p>
          </div>
        ) : (
          <div>
            <button
              onClick={handleLogin}
              className="group relative w-full flex justify-center py-3 px-4 border border-transparent text-sm font-medium rounded-md text-white bg-purple-600 hover:bg-purple-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-purple-500 transition-colors"
              disabled={oidcStatus === 'checking'}
            >
              Sign in with OIDC
            </button>
          </div>
        )}

        <div className="text-center text-xs text-gray-500">
          <p>Protected by Keycloak authentication</p>
        </div>
      </div>
    </div>
  );
};

export default Login;
