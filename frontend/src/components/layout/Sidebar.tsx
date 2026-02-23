/**
 * Sidebar navigation with Flowbite - Mobile responsive with hamburger menu
 */
import { Sidebar as FlowbiteSidebar } from 'flowbite-react';
import { Link, useLocation } from 'react-router-dom';
import {
  HiHome,
  HiServer,
  HiLogout,
  HiGlobe,
  HiDownload,
  HiUserGroup,
  HiUsers,
  HiMail,
} from 'react-icons/hi';
import { FaGithub } from 'react-icons/fa';
import { usePermissions } from '../../contexts/PermissionContext';

interface SidebarProps {
  onLogout: () => void;
  isOpen: boolean;
  onClose: () => void;
}

export function Sidebar({ onLogout, isOpen, onClose }: SidebarProps) {
  const location = useLocation();
  const { isSystemAdmin, isNetworkOwner } = usePermissions();

  const handleItemClick = () => {
    if (window.innerWidth < 1650) {
      onClose();
    }
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
                to="/groups"
                icon={HiUserGroup}
                active={location.pathname === '/groups'}
                onClick={handleItemClick}
              >
                Groups
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

              {/* System Admin Only */}
              {isSystemAdmin && (
                <FlowbiteSidebar.Item
                  as={Link}
                  to="/users"
                  icon={HiUsers}
                  active={location.pathname === '/users'}
                  onClick={handleItemClick}
                >
                  Users
                </FlowbiteSidebar.Item>
              )}

              {/* Network Owners and System Admins */}
              {(isNetworkOwner || isSystemAdmin) && (
                <FlowbiteSidebar.Item
                  as={Link}
                  to="/invitations"
                  icon={HiMail}
                  active={location.pathname === '/invitations'}
                  onClick={handleItemClick}
                >
                  Invitations
                </FlowbiteSidebar.Item>
              )}
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
