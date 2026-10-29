/**
 * App-wide notices: the instance is moving (read-only), and a nudge to turn on
 * two-factor for accounts without it (dismissed per browser for 30 days).
 */
import { useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { Alert } from 'flowbite-react';
import { HiShieldExclamation, HiSwitchHorizontal } from 'react-icons/hi';
import { useAuth } from '../../contexts/AuthContext';

const DISMISS_KEY = 'nebula_commander_2fa_nudge_dismissed_at';
const DISMISS_DAYS = 30;

function dismissedRecently(): boolean {
  try {
    const at = Number(localStorage.getItem(DISMISS_KEY) || 0);
    return Date.now() - at < DISMISS_DAYS * 24 * 3600 * 1000;
  } catch {
    return false;
  }
}

export function Banners() {
  const { user } = useAuth();
  const location = useLocation();
  const [dismissed, setDismissed] = useState(dismissedRecently);

  const dismiss = () => {
    try {
      localStorage.setItem(DISMISS_KEY, String(Date.now()));
    } catch {
      // storage blocked: hide for this page load only
    }
    setDismissed(true);
  };

  const showNudge = user && !user.two_factor_enabled && !dismissed && location.pathname !== '/settings/security';

  return (
    <>
      {user?.moving_to && (
        <Alert color="warning" icon={HiSwitchHorizontal} className="mb-4">
          This server is moving to <strong className="break-all">{user.moving_to}</strong> and is read-only until the
          move is done or cancelled.
        </Alert>
      )}
      {showNudge && (
        <Alert color="info" icon={HiShieldExclamation} className="mb-4" onDismiss={dismiss}>
          Protect your account with two-factor authentication.{' '}
          <Link to="/settings/security" className="underline font-medium">Set it up</Link>
        </Alert>
      )}
    </>
  );
}
