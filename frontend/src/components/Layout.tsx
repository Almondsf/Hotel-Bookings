import { Suspense } from 'react';
import { NavLink, Outlet } from 'react-router-dom';

import type { Capability } from '../api/types';
import { useAuth } from '../auth/AuthContext';
import { humanize } from '../lib/format';
import { Loading } from './ui';

type Need = Capability | Capability[];

/** True when the user has the capability, or any of them for a list. */
export const allows = (can: (c: Capability) => boolean, need: Need) => (Array.isArray(need) ? need.some(can) : can(need));

export const SETTINGS_CAPABILITIES: Capability[] = ['rooms.manage', 'rates.manage', 'pos.manage', 'billing.configure'];

export const NAV: { to: string; label: string; capability: Need }[] = [
  { to: '/dashboard', label: 'Dashboard', capability: 'bookings.view' },
  { to: '/room-board', label: 'Room board', capability: 'bookings.view' },
  { to: '/reservations', label: 'Reservations', capability: 'bookings.view' },
  { to: '/reservations/new', label: 'New reservation', capability: 'bookings.manage' },
  { to: '/guests', label: 'Guests', capability: 'bookings.view' },
  { to: '/folios', label: 'Folios', capability: 'folios.view' },
  { to: '/companies', label: 'Companies', capability: 'folios.view' },
  { to: '/housekeeping', label: 'Housekeeping', capability: 'housekeeping.view' },
  { to: '/maintenance', label: 'Maintenance', capability: 'maintenance.view' },
  { to: '/pos', label: 'Point of sale', capability: 'pos.use' },
  { to: '/reports', label: 'Reports', capability: 'reports.view' },
  { to: '/night-audit', label: 'Night audit', capability: 'night_audit.run' },
  { to: '/channels', label: 'Online channels', capability: 'rates.manage' },
  { to: '/settings', label: 'Settings', capability: SETTINGS_CAPABILITIES },
  { to: '/staff', label: 'Staff', capability: 'staff.manage' },
  { to: '/audit', label: 'Audit log', capability: 'audit.view' },
];

export function Layout() {
  const { user, can, logout } = useAuth();
  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">Hotel <span>PMS</span></div>
        <nav aria-label="Main">
          {NAV.filter((item) => allows(can, item.capability)).map((item) => (
            <NavLink key={item.to} to={item.to} end={item.to === '/dashboard' || item.to === '/reservations'}>
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="who">
          {user?.first_name} {user?.last_name}
          <small>{humanize(user?.role ?? '')} · <NavLink to="/account" style={{ color: 'inherit' }}>My account</NavLink></small>
          <button style={{ marginTop: 10 }} onClick={() => void logout()}>Sign out</button>
        </div>
      </aside>
      <main className="main">
        <Suspense fallback={<Loading />}>
          <Outlet />
        </Suspense>
      </main>
    </div>
  );
}
