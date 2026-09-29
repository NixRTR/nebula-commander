import React, { createContext, useContext, useState, useCallback } from 'react';
import { Toast, ToastMessage, ToastType } from '../components/Toast';

interface ToastContextType {
  showToast: (type: ToastType, title: string, message?: string, duration?: number) => string;
  dismissToast: (id: string) => void;
  updateToast: (id: string, updates: Partial<ToastMessage>) => void;
}

const ToastContext = createContext<ToastContextType | undefined>(undefined);

export const ToastProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [toasts, setToasts] = useState<ToastMessage[]>([]);

  const showToast = useCallback((
    type: ToastType,
    title: string,
    message?: string,
    duration: number = 5000
  ): string => {
    const id = `toast-${Date.now()}-${Math.random()}`;
    const newToast: ToastMessage = { id, type, title, message, duration };
    setToasts((prev) => [...prev, newToast]);
    return id;
  }, []);

  const dismissToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((toast) => toast.id !== id));
  }, []);

  const updateToast = useCallback((id: string, updates: Partial<ToastMessage>) => {
    setToasts((prev) =>
      prev.map((toast) => (toast.id === id ? { ...toast, ...updates } : toast))
    );
  }, []);

  return (
    <ToastContext.Provider value={{ showToast, dismissToast, updateToast }}>
      {children}
      {/* Above Flowbite modals (z-50) and the onboarding overlay (z-[100]), so an
          error raised from inside a modal is never hidden behind it. */}
      <div className="fixed top-4 right-4 z-[200] flex flex-col gap-2">
        {toasts.map((toast) => (
          <Toast key={toast.id} toast={toast} onDismiss={dismissToast} />
        ))}
      </div>
    </ToastContext.Provider>
  );
};

// eslint-disable-next-line react-refresh/only-export-components
export const useToast = () => {
  const context = useContext(ToastContext);
  if (!context) {
    throw new Error('useToast must be used within ToastProvider');
  }
  return context;
};

/**
 * Drop-in replacement for a page's `const [error, setError] = useState<string | null>(null)`
 * when the error was only ever rendered as a banner: shows each message as an error toast
 * that stays until dismissed, instead of an inline banner an open modal would cover.
 * `setError(null)` is a no-op, so existing call sites keep working unchanged.
 */
// eslint-disable-next-line react-refresh/only-export-components
export const useErrorToast = () => {
  const { showToast } = useToast();
  return useCallback(
    (message: string | null) => {
      if (message) showToast('error', 'Error', message, 0);
    },
    [showToast]
  );
};
