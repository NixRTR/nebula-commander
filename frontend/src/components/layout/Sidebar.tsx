/**
 * Sidebar navigation with Flowbite - Mobile responsive with hamburger menu
 */
import { useState, useEffect } from 'react';
import { Sidebar as FlowbiteSidebar } from 'flowbite-react';
import { Link, useLocation } from 'react-router-dom';
import {
  HiHome,
  HiServer,
  HiCog,
  HiShieldCheck,
  HiLogout,
  HiGlobe,
  HiDownload,
} from 'react-icons/hi';
import { FaGithub } from 'react-icons/fa';

const SIDEBAR_STORAGE_KEY = 'nebula-commander-sidebar-expanded';

function loadSidebarExpanded(): { settings: boolean } {
  try {
    const s = localStorage.getItem(SIDEBAR_STORAGE_KEY);
    if (s) {
      const o = JSON.parse(s) as Record<string, boolean>;
      return { settings: !!o.settings };
    }
  } catch {
    // ignore
  }
  return { settings: false };
}

function saveSidebarExpanded(expanded: { settings: boolean }) {
  try {
    localStorage.setItem(SIDEBAR_STORAGE_KEY, JSON.stringify(expanded));
  } catch {
    // ignore
  }
}

interface SidebarProps {
  onLogout: () => void;
  isOpen: boolean;
  onClose: () => void;
}

export function Sidebar({ onLogout, isOpen, onClose }: SidebarProps) {
  const location = useLocation();
  const [settingsExpanded, setSettingsExpanded] = useState(() => loadSidebarExpanded().settings);

  const handleItemClick = () => {
    if (window.innerWidth < 1650) {
      onClose();
    }
  };

  const isActive = (path: string) => location.pathname === path;
  const isParentActive = (path: string, children?: Array<{ path: string }>) => {
    if (isActive(path)) return true;
    if (children) {
      return children.some(child => location.pathname.startsWith(child.path) || location.pathname === child.path);
    }
    return false;
  };

  const settingsChildren = [
    { path: '/settings/oidc', label: 'OIDC Config', icon: HiShieldCheck },
    { path: '/settings/system', label: 'System', icon: HiCog },
  ];

  const isSettingsActive = isParentActive('/settings', settingsChildren);

  // Auto-expand only the section for the current route (defer to avoid synchronous setState in effect)
  useEffect(() => {
    const id = setTimeout(() => {
      if (isSettingsActive) {
        setSettingsExpanded(true);
        saveSidebarExpanded({ settings: true });
      }
    }, 0);
    return () => clearTimeout(id);
  }, [isSettingsActive]);

  const toggleSettings = () => {
    setSettingsExpanded((prev: boolean) => {
      const next = !prev;
      saveSidebarExpanded({ settings: next });
      return next;
    });
  };

  return (
    <>
      {/* Overlay - visible below 1650px */}
      {isOpen && (
        <div
          className="fixed inset-0 bg-black bg-opacity-50 z-40 xl-custom:hidden"
          onClick={onClose}
        />
      )}

      {/* Sidebar */}
      <div
        className={`
          fixed xl-custom:static inset-y-0 left-0 z-50
          transform transition-transform duration-300 ease-in-out
          xl-custom:transform-none
          ${isOpen ? 'translate-x-0' : '-translate-x-full xl-custom:translate-x-0'}
        `}
      >
        <FlowbiteSidebar aria-label="Sidebar with navigation" className="h-full">
          <FlowbiteSidebar.Items>
            <FlowbiteSidebar.ItemGroup>
              <FlowbiteSidebar.Item
                as={Link}
                to="/"
                icon={HiHome}
                active={location.pathname === '/'}
                onClick={handleItemClick}
              >
                Home
              </FlowbiteSidebar.Item>

              <FlowbiteSidebar.Item
                as={Link}
                to="/networks"
                icon={HiGlobe}
                active={location.pathname === '/networks'}
                onClick={handleItemClick}
                data-onboarding-target="sidebar-networks"
              >
                Networks
              </FlowbiteSidebar.Item>

              <FlowbiteSidebar.Item
                as={Link}
                to="/nodes"
                icon={HiServer}
                active={location.pathname === '/nodes'}
                onClick={handleItemClick}
                data-onboarding-target="sidebar-nodes"
              >
                Nodes
              </FlowbiteSidebar.Item>

              <FlowbiteSidebar.Item
                as={Link}
                to="/client-download"
                icon={HiDownload}
                active={location.pathname === '/client-download'}
                onClick={handleItemClick}
                data-onboarding-target="sidebar-client-download"
              >
                Client Download
              </FlowbiteSidebar.Item>

              {/* Settings - collapsible */}
              <li>
                <button
                  type="button"
                  onClick={toggleSettings}
                  className={`flex items-center w-full p-2 rounded-lg ${
                    isSettingsActive
                      ? 'text-blue-600 bg-blue-50 dark:text-blue-500 dark:bg-gray-700'
                      : 'text-gray-900 hover:bg-gray-100 dark:text-white dark:hover:bg-gray-700'
                  }`}
                >
                  <HiCog className="w-5 h-5 mr-3" />
                  <span>Settings</span>
                </button>
                {settingsExpanded && (
                  <ul className="ml-6 mt-2 space-y-1">
                    {settingsChildren.map((child) => {
                      const IconComponent = child.icon;
                      return (
                        <li key={child.path}>
                          <Link
                            to={child.path}
                            onClick={handleItemClick}
                            className={`flex items-center p-2 rounded-lg text-sm ${
                              isActive(child.path)
                                ? 'text-blue-600 bg-blue-50 dark:text-blue-500 dark:bg-gray-700'
                                : 'text-gray-700 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-gray-700'
                            }`}
                          >
                            <IconComponent className="w-4 h-4 mr-2" />
                            {child.label}
                          </Link>
                        </li>
                      );
                    })}
                  </ul>
                )}
              </li>
            </FlowbiteSidebar.ItemGroup>

            <FlowbiteSidebar.ItemGroup>
              <FlowbiteSidebar.Item
                icon={HiLogout}
                style={{ cursor: 'pointer' }}
                onClick={() => {
                  handleItemClick();
                  onLogout();
                }}
              >
                Logout
              </FlowbiteSidebar.Item>
              <FlowbiteSidebar.Item
                href="https://github.com/NixRTR/nebula-commander"
                target="_blank"
                rel="noopener noreferrer"
                icon={FaGithub}
                as="a"
              >
                GitHub
              </FlowbiteSidebar.Item>
            </FlowbiteSidebar.ItemGroup>
          </FlowbiteSidebar.Items>
        </FlowbiteSidebar>
      </div>
    </>
  );
}
