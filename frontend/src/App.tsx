import { lazy, Suspense, type ReactNode } from 'react';
import { Navigate, Route, Routes } from 'react-router-dom';

import type { Capability } from './api/types';
import { useAuth } from './auth/AuthContext';
import { Layout, NAV } from './components/Layout';
import { Loading } from './components/ui';
import { Login } from './pages/Login';
import { ForgotPassword, SetPassword } from './pages/PasswordPages';

const guestPage = (name: 'SearchPage' | 'CheckoutPage' | 'PaymentCompletePage' | 'ManageBookingPage') =>
  lazy(() => import('./guest/GuestSite').then((m) => ({ default: m[name] })));
const GuestSearch = guestPage('SearchPage');
const GuestCheckout = guestPage('CheckoutPage');
const GuestPaymentComplete = guestPage('PaymentCompletePage');
const GuestManageBooking = guestPage('ManageBookingPage');
const GuestHome = lazy(() => import('./guest/HomePage').then((m) => ({ default: m.HomePage })));
const GuestRoom = lazy(() => import('./guest/RoomPage').then((m) => ({ default: m.RoomPage })));

// Pages load on demand: guests on the booking site never download the staff portal, and
// staff only download the screens they open.
const Account = lazy(() => import('./pages/Account').then((m) => ({ default: m.Account })));
const Channels = lazy(() => import('./pages/Admin').then((m) => ({ default: m.Channels })));
const AuditLog = lazy(() => import('./pages/Admin').then((m) => ({ default: m.AuditLog })));
const Staff = lazy(() => import('./pages/Admin').then((m) => ({ default: m.Staff })));
const Dashboard = lazy(() => import('./pages/Dashboard').then((m) => ({ default: m.Dashboard })));
const FolioDetail = lazy(() => import('./pages/Folios').then((m) => ({ default: m.FolioDetail })));
const Folios = lazy(() => import('./pages/Folios').then((m) => ({ default: m.Folios })));
const Accounts = lazy(() => import('./pages/Accounts').then((m) => ({ default: m.Accounts })));
const AccountDetail = lazy(() => import('./pages/Accounts').then((m) => ({ default: m.AccountDetail })));
const GuestDetail = lazy(() => import('./pages/Guests').then((m) => ({ default: m.GuestDetail })));
const Guests = lazy(() => import('./pages/Guests').then((m) => ({ default: m.Guests })));
const NewReservation = lazy(() => import('./pages/NewReservation').then((m) => ({ default: m.NewReservation })));
const Housekeeping = lazy(() => import('./pages/Operations').then((m) => ({ default: m.Housekeeping })));
const Maintenance = lazy(() => import('./pages/Operations').then((m) => ({ default: m.Maintenance })));
const Pos = lazy(() => import('./pages/Pos').then((m) => ({ default: m.Pos })));
const ReservationDetail = lazy(() => import('./pages/ReservationDetail').then((m) => ({ default: m.ReservationDetail })));
const Reservations = lazy(() => import('./pages/Reservations').then((m) => ({ default: m.Reservations })));
const Ledgers = lazy(() => import('./pages/Reports').then((m) => ({ default: m.Ledgers })));
const NightAudit = lazy(() => import('./pages/Reports').then((m) => ({ default: m.NightAudit })));
const Reports = lazy(() => import('./pages/Reports').then((m) => ({ default: m.Reports })));
const RoomBoard = lazy(() => import('./pages/RoomBoard').then((m) => ({ default: m.RoomBoard })));

function RequireAuth({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  if (loading) return <Loading />;
  return user ? <>{children}</> : <Navigate to="/login" replace />;
}

function Guard({ capability, children }: { capability: Capability; children: ReactNode }) {
  const { can } = useAuth();
  return can(capability) ? <>{children}</> : <div className="empty">You don't have access to this page.</div>;
}

/** Send each role to its first page: front desk to the dashboard, housekeeping to their task list, etc. */
function Home() {
  const { can, user } = useAuth();
  // Staff whose role requires two-factor sign-in land on enrolment until it's done
  if (user?.mfa_required && !user.mfa_enabled && !user.capabilities.length) return <Navigate to="/account" replace />;
  if (can('bookings.view')) return <Dashboard />;
  const first = NAV.find((item) => item.to !== '/dashboard' && can(item.capability));
  return first ? <Navigate to={first.to} replace /> : <div className="empty">Your account has no pages assigned yet.</div>;
}

export function App() {
  return (
    <Routes>
      <Route path="/" element={<Suspense fallback={<Loading />}><GuestHome /></Suspense>} />
      <Route path="/rooms/:slug" element={<Suspense fallback={<Loading />}><GuestRoom /></Suspense>} />
      <Route path="/book" element={<Suspense fallback={<Loading />}><GuestSearch /></Suspense>} />
      <Route path="/book/checkout" element={<Suspense fallback={<Loading />}><GuestCheckout /></Suspense>} />
      <Route path="/booking/payment-complete" element={<Suspense fallback={<Loading />}><GuestPaymentComplete /></Suspense>} />
      <Route path="/booking/manage" element={<Suspense fallback={<Loading />}><GuestManageBooking /></Suspense>} />
      <Route path="/login" element={<Login />} />
      <Route path="/forgot-password" element={<ForgotPassword />} />
      <Route path="/set-password" element={<SetPassword />} />
      <Route element={<RequireAuth><Suspense fallback={<Loading />}><Layout /></Suspense></RequireAuth>}>
        <Route path="dashboard" element={<Home />} />
        <Route path="room-board" element={<Guard capability="bookings.view"><RoomBoard /></Guard>} />
        <Route path="reservations" element={<Guard capability="bookings.view"><Reservations /></Guard>} />
        <Route path="reservations/new" element={<Guard capability="bookings.manage"><NewReservation /></Guard>} />
        <Route path="reservations/:id" element={<Guard capability="bookings.view"><ReservationDetail /></Guard>} />
        <Route path="guests" element={<Guard capability="bookings.view"><Guests /></Guard>} />
        <Route path="guests/:id" element={<Guard capability="bookings.view"><GuestDetail /></Guard>} />
        <Route path="folios" element={<Guard capability="folios.view"><Folios /></Guard>} />
        <Route path="folios/:id" element={<Guard capability="folios.view"><FolioDetail /></Guard>} />
        <Route path="companies" element={<Guard capability="folios.view"><Accounts /></Guard>} />
        <Route path="companies/:id" element={<Guard capability="folios.view"><AccountDetail /></Guard>} />
        <Route path="housekeeping" element={<Guard capability="housekeeping.view"><Housekeeping /></Guard>} />
        <Route path="maintenance" element={<Guard capability="maintenance.view"><Maintenance /></Guard>} />
        <Route path="pos" element={<Guard capability="pos.use"><Pos /></Guard>} />
        <Route path="reports" element={<Guard capability="reports.view"><Reports /></Guard>} />
        <Route path="reports/ledgers" element={<Guard capability="reports.view"><Ledgers /></Guard>} />
        <Route path="night-audit" element={<Guard capability="night_audit.run"><NightAudit /></Guard>} />
        <Route path="channels" element={<Guard capability="bookings.view"><Channels /></Guard>} />
        <Route path="account" element={<Account />} />
        <Route path="staff" element={<Guard capability="staff.manage"><Staff /></Guard>} />
        <Route path="audit" element={<Guard capability="audit.view"><AuditLog /></Guard>} />
        <Route path="*" element={<div className="empty">Page not found.</div>} />
      </Route>
    </Routes>
  );
}
