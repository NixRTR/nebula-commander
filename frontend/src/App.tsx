import { lazy, Suspense, useState } from "react";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { Sidebar } from "./components/layout/Sidebar";
import { Navbar } from "./components/layout/Navbar";
import { OnboardingProvider } from "./contexts/OnboardingContext";
import { OnboardingOverlay } from "./components/onboarding/OnboardingOverlay";

// Lazy load pages for code splitting - reduces initial bundle size
const Home = lazy(() => import("./pages/Home").then(m => ({ default: m.Home })));
const Networks = lazy(() => import("./pages/Networks").then(m => ({ default: m.Networks })));
const Groups = lazy(() => import("./pages/Groups").then(m => ({ default: m.Groups })));
const Nodes = lazy(() => import("./pages/Nodes").then(m => ({ default: m.Nodes })));
const ClientDownload = lazy(() => import("./pages/ClientDownload").then(m => ({ default: m.ClientDownload })));
// Loading fallback component
const PageLoader = () => (
  <div className="flex items-center justify-center h-screen">
    <div className="text-gray-600 dark:text-gray-400">Loading...</div>
  </div>
);

export default function App() {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const username = "admin"; // TODO: Get from auth context
  const connectionStatus = "connected"; // TODO: Get from WebSocket/API

  const handleLogout = () => {
    // TODO: Implement logout
    console.log("Logout");
  };

  return (
    <BrowserRouter>
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
                  <Route path="/groups" element={<Groups />} />
                  <Route path="/nodes" element={<Nodes />} />
                  <Route path="/client-download" element={<ClientDownload />} />
                  <Route path="/settings/oidc" element={<Home />} />
                  <Route path="/settings/system" element={<Home />} />
                </Routes>
              </Suspense>
            </main>
          </div>
        </div>
        <OnboardingOverlay />
      </OnboardingProvider>
    </BrowserRouter>
  );
}
