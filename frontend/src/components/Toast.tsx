import React from 'react';
import { Toast as FlowbiteToast } from 'flowbite-react';
import { HiCheck, HiX, HiExclamation } from 'react-icons/hi';
import { ImSpinner2 } from 'react-icons/im';

export type ToastType = 'success' | 'error' | 'warning' | 'info' | 'loading';

export interface ToastMessage {
  id: string;
  type: ToastType;
  title: string;
  message?: string;
  duration?: number; // Auto-dismiss after ms (0 = no auto-dismiss)
}

interface ToastProps {
  toast: ToastMessage;
  onDismiss: (id: string) => void;
}

export const Toast: React.FC<ToastProps> = ({ toast, onDismiss }) => {
  const getIcon = () => {
    switch (toast.type) {
      case 'success':
        return <HiCheck className="h-5 w-5" />;
      case 'error':
        return <HiX className="h-5 w-5" />;
      case 'warning':
        return <HiExclamation className="h-5 w-5" />;
      case 'loading':
        return <ImSpinner2 className="h-5 w-5 animate-spin" />;
      default:
        return <HiExclamation className="h-5 w-5" />;
    }
  };

  const getColor = () => {
    switch (toast.type) {
      case 'success':
        return 'bg-green-100 text-green-500 dark:bg-green-800 dark:text-green-200';
      case 'error':
        return 'bg-red-100 text-red-500 dark:bg-red-800 dark:text-red-200';
      case 'warning':
        return 'bg-yellow-100 text-yellow-500 dark:bg-yellow-800 dark:text-yellow-200';
      case 'loading':
        return 'bg-purple-100 text-purple-600 dark:bg-purple-800 dark:text-purple-200';
      default:
        return 'bg-gray-100 text-gray-500 dark:bg-gray-800 dark:text-gray-200';
    }
  };

  React.useEffect(() => {
    if (toast.duration && toast.duration > 0 && toast.type !== 'loading') {
      const timer = setTimeout(() => {
        onDismiss(toast.id);
      }, toast.duration);
      return () => clearTimeout(timer);
    }
  }, [toast.id, toast.duration, toast.type, onDismiss]);

  return (
    <FlowbiteToast>
      <div className={`inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg ${getColor()}`}>
        {getIcon()}
      </div>
      <div className="ml-3 text-sm font-normal">
        <span className="mb-1 text-sm font-semibold text-gray-900 dark:text-white">
          {toast.title}
        </span>
        {toast.message && (
          <div className="mb-2 text-sm font-normal">
            {toast.message}
          </div>
        )}
      </div>
      {toast.type !== 'loading' && (
        <FlowbiteToast.Toggle onDismiss={() => onDismiss(toast.id)} />
      )}
    </FlowbiteToast>
  );
};
