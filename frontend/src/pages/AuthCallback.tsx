import React, { useEffect } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { exchangeAuthCode } from '../api/client';

const AuthCallback: React.FC = () => {
  const { setToken } = useAuth();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();

  useEffect(() => {
    // Get the one-time exchange code from URL query params (set by backend redirect)
    const code = searchParams.get('code');

    if (!code) {
      navigate('/login?error=no_token', { replace: true });
      return;
    }

    exchangeAuthCode(code)
      .then((token) => {
        setToken(token);
        const returnUrl = localStorage.getItem('invitation_return_url');
        if (returnUrl) {
          localStorage.removeItem('invitation_return_url');
          navigate(returnUrl, { replace: true });
        } else {
          navigate('/', { replace: true });
        }
      })
      .catch(() => {
        navigate('/login?error=no_token', { replace: true });
      });
  }, [searchParams, setToken, navigate]);

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-900">
      <div className="text-center">
        <div className="inline-block animate-spin rounded-full h-12 w-12 border-b-2 border-blue-500"></div>
        <p className="mt-4 text-gray-400">Completing authentication...</p>
      </div>
    </div>
  );
};

export default AuthCallback;
