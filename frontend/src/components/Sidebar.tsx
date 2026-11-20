import { ORG_LOGO, ORG_NAME } from '../lib/branding';
import React from 'react';
import { NavLink, useLocation } from 'react-router-dom';
import {
  LayoutDashboard,
  Settings,
  Briefcase,
  LogOut,
  ChevronRight,
} from 'lucide-react';
import { useAuth } from '../context/AuthContext';

const NAV_ITEMS = [
  { to: '/', end: true, icon: LayoutDashboard, label: 'Dashboard' },
  { to: '/recruitment', end: false, icon: Briefcase, label: 'Job Profiles' },
];

export const Sidebar: React.FC = () => {
  const { user, logout } = useAuth();
  const displayName = user?.email ? user.email.split('@')[0] : 'HR';
  const initials = displayName.slice(0, 2).toUpperCase();

  return (
    <div className="fixed z-20 bg-card border-border inset-x-0 bottom-0 border-t flex flex-row pb-[env(safe-area-inset-bottom)] lg:inset-x-auto lg:left-0 lg:top-0 lg:w-64 lg:h-screen lg:flex-col lg:border-t-0 lg:border-r lg:pb-0">
      {/* Branding */}
      <div className="hidden lg:flex px-5 py-5 border-b border-border items-center gap-3">
        <div className="w-10 h-10 rounded-lg bg-primary flex items-center justify-center shrink-0 shadow-sm">
          {ORG_LOGO ? (
            <img src={ORG_LOGO} alt={ORG_NAME} className="w-7 h-7 object-contain" />
          ) : (
            <span className="text-primary-foreground font-bold text-sm">{ORG_NAME.slice(0, 3).toUpperCase()}</span>
          )}
        </div>
        <div className="min-w-0">
          <h1 className="font-bold text-foreground text-sm leading-tight">RecruitAI Validator</h1>
          <span className="text-xs font-normal text-muted">{ORG_NAME} screening</span>
        </div>
      </div>

      {/* Main nav */}
      <nav className="flex-1 px-1 py-1 flex flex-row gap-0.5 lg:px-3 lg:py-4 lg:flex-col lg:overflow-y-auto">
        <span className="hidden lg:block px-2 mb-2 text-xs text-muted">Main</span>
        {NAV_ITEMS.map(({ to, end, icon: Icon, label }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            className={({ isActive }) =>
              `group relative flex flex-1 flex-col items-center justify-center gap-1 px-1 py-2 rounded-lg text-xs font-medium lg:flex-none lg:flex-row lg:justify-start lg:gap-3 lg:px-3 lg:py-2.5 lg:text-base transition-all duration-150 ${
                isActive
                  ? 'bg-primary/10 text-primary'
                  : 'text-foreground hover:bg-accent'
              }`
            }
          >
            {({ isActive }) => (
              <>
                {isActive && (
                  <span className="hidden lg:block absolute left-0 top-1/2 -translate-y-1/2 w-1 h-5 bg-primary rounded-r-full" />
                )}
                <Icon className={`w-4.5 h-4.5 shrink-0 transition-colors ${isActive ? 'text-primary' : 'text-muted group-hover:text-foreground'}`} />
                <span className="lg:flex-1">{label}</span>
                {isActive && <ChevronRight className="hidden lg:block w-3.5 h-3.5 text-primary/50" />}
              </>
            )}
          </NavLink>
        ))}
      </nav>

      {/* Account section */}
      <div className="flex flex-row gap-0.5 px-1 py-1 lg:flex-col lg:px-3 lg:pb-4 lg:pt-3 lg:border-t lg:border-border">
        {/* User chip */}
        <div className="hidden lg:flex items-center gap-2.5 px-3 py-2 mb-1">
          <div className="w-8 h-8 rounded-full bg-primary/10 text-primary border border-primary/20 flex items-center justify-center font-bold text-xs shrink-0">
            {initials}
          </div>
          <div className="min-w-0">
            <p className="text-sm font-semibold text-foreground truncate capitalize">{displayName}</p>
            <p className="text-xs text-foreground font-normal truncate">{user?.email}</p>
          </div>
        </div>

        <NavLink
          to="/settings"
          className={({ isActive }) =>
            `flex flex-col items-center justify-center gap-1 px-2 py-2 rounded-lg text-xs font-medium lg:flex-row lg:justify-start lg:gap-3 lg:px-3 lg:py-2.5 lg:text-base transition-all duration-150 ${
              isActive ? 'bg-primary/10 text-primary' : 'text-foreground hover:bg-accent'
            }`
          }
        >
          <Settings className="w-4.5 h-4.5" />
          Preferences
        </NavLink>

        <button
          onClick={() => logout()}
          className="flex flex-col items-center justify-center gap-1 px-2 py-2 rounded-lg text-xs font-medium text-danger hover:bg-danger/10 transition-all duration-150 lg:flex-row lg:justify-start lg:gap-3 lg:px-3 lg:py-2.5 lg:text-base lg:text-left lg:w-full lg:mt-1"
        >
          <LogOut className="w-4.5 h-4.5 shrink-0" />
          Sign out
        </button>
      </div>
    </div>
  );
};

export default Sidebar;
