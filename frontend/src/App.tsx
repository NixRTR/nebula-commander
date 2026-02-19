import { lazy, Suspense, useState, useEffect } from "react";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { Sidebar } from "./components/layout/Sidebar";
import { Navbar } from "./components/layout/Navbar";
import { OnboardingProvider } from "./contexts/OnboardingContext";
import { AuthProvider, useAuth } from "./contexts/AuthContext";
import { PermissionProvider } from "./contexts/PermissionContext";
import { ToastProvider } from "./contexts/ToastContext";
import { OnboardingOverlay } from "./components/onboarding/OnboardingOverlay";
import { initializeTokenRefresh } from "./api/client";
import ProtectedRoute from "./components/ProtectedRoute";

// Lazy load pages for code splitting - reduces initial bundle size
const Home = lazy(() => import("./pages/Home").then(m => ({ default: m.Home })));
const Networks = lazy(() => import("./pages/Networks").then(m => ({ default: m.Networks })));
const Groups = lazy(() => import("./pages/Groups").then(m => ({ default: m.Groups })));
const Nodes = lazy(() => import("./pages/Nodes").then(m => ({ default: m.Nodes })));
const ClientDownload = lazy(() => import("./pages/ClientDownload").then(m => ({ default: m.ClientDownload })));
const Users = lazy(() => import("./pages/Users").then(m => ({ default: m.Users })));
const Invitations = lazy(() => import("./pages/Invitations").then(m => ({ default: m.Invitations })));
const NetworkUsers = lazy(() => import("./pages/NetworkUsers").then(m => ({ default: m.NetworkUsers })));
const AcceptInvitation = lazy(() => import("./pages/AcceptInvitation").then(m => ({ default: m.AcceptInvitation })));
const ReauthComplete = lazy(() => import("./pages/ReauthComplete").then(m => ({ default: m.ReauthComplete })));
const Login = lazy(() => import("./pages/Login"));
const AuthCallback = lazy(() => import("./pages/AuthCallback"));
// Loading fallback component
const PageLoader = () => (
  <div className="flex items-center justify-center h-screen">
    <div className="text-gray-600 dark:text-gray-400">Loading...</div>
  </div>
);

function AppContent() {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const { user, logout } = useAuth();
  const username = user?.name || user?.email || user?.sub || "User";
  const connectionStatus = "connected"; // TODO: Get from WebSocket/API

  // Initialize automatic token refresh on app startup
  useEffect(() => {
    initializeTokenRefresh();
  }, []);

  const handleLogout = () => {
    logout();
  };

  return (
    <PermissionProvider>
      <ToastProvider>
        <OnboardingProvider>
          <div className="flex h-screen">
          <Sidebar
            onLogout={handleLogout}
            isOpen={sidebarOpen}
            onClose={() => setSidebarOpen(false)}
          />

          <div className="flex-1 flex flex-col overflow-hidden">
            <Navbar
              username={username}
              connectionStatus={connectionStatus}
              onMenuClick={() => setSidebarOpen(!sidebarOpen)}
            />

            <main className="flex-1 overflow-y-auto p-6 bg-gray-50 dark:bg-gray-900">
              <Suspense fallback={<PageLoader />}>
                <Routes>
                  <Route path="/" element={<Home />} />
                  <Route path="/networks" element={<Networks />} />
                  <Route path="/networks/:networkId/users" element={<NetworkUsers />} />
                  <Route path="/groups" element={<Groups />} />
                  <Route path="/nodes" element={<Nodes />} />
                  <Route path="/client-download" element={<ClientDownload />} />
                  <Route path="/users" element={<Users />} />
                  <Route path="/invitations" element={<Invitations />} />
                  <Route path="/reauth/complete" element={<ReauthComplete />} />
                  <Route path="/auth/reauth/complete" element={<ReauthComplete />} />
                  <Route path="/settings/oidc" element={<Home />} />
                  <Route path="/settings/system" element={<Home />} />
                </Routes>
              </Suspense>
            </main>
          </div>
        </div>
        <OnboardingOverlay />
        </OnboardingProvider>
      </ToastProvider>
    </PermissionProvider>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Suspense fallback={<PageLoader />}>
          <Routes>
            {/* Public routes */}
            <Route path="/login" element={<Login />} />
            <Route path="/auth/callback" element={<AuthCallback />} />
            <Route path="/invitations/accept/:token" element={<AcceptInvitation />} />
            
            {/* Protected routes */}
            <Route path="/*" element={
              <ProtectedRoute>
                <AppContent />
              </ProtectedRoute>
            } />
          </Routes>
        </Suspense>
      </AuthProvider>
    </BrowserRouter>
  );
}
