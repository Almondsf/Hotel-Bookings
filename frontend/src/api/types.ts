export type Capability =
  | 'rooms.manage' | 'staff.manage' | 'audit.view' | 'bookings.view' | 'bookings.manage'
  | 'guests.view_identity' | 'folios.view' | 'folios.post' | 'folios.adjust' | 'payments.take'
  | 'payments.refund' | 'accounts.manage' | 'billing.configure' | string;

export interface User {
  id: number;
  email: string;
  first_name: string;
  last_name: string;
  phone: string;
  role: string;
  capabilities: Capability[];
  mfa_enabled: boolean;
  mfa_required: boolean;
}

export interface Paginated<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

export interface Guest {
  id: number;
  first_name: string;
  last_name: string;
  email: string;
  phone_number: string | null;
  address?: string | null;
  country?: string | null;
  nationality?: string;
  company_name?: string;
  is_vip?: boolean;
  notes?: string;
  has_valid_identification?: boolean;
}

export type BookingStatus = 'PENDING' | 'CONFIRMED' | 'CHECKED_IN' | 'CHECKED_OUT' | 'CANCELLED' | 'NO_SHOW';

export interface Reservation {
  id: number;
  confirmation_number: string;
  folio: { id: number; number: string; status: string; balance: string } | null;
  group_reference: string | null;
  status: BookingStatus;
  source: string;
  guest: Guest;
  room: number;
  room_number: string;
  room_type: number;
  room_type_name: string;
  check_in_date: string;
  check_out_date: string;
  nights: number;
  number_of_adults: number;
  number_of_children: number;
  special_requests: string | null;
  price_per_night: string;
  total_price: string;
  taxes: string;
  total_with_taxes: string;
  cancellation_policy: string;
  cancellation_fee_if_cancelled_now: string | null;
  penalty_amount: string;
  penalty_waived: boolean;
  cancellation_reason: string;
  created_by: string | null;
  created_at: string;
}

export interface Summary {
  date: string;
  arrivals_expected: number;
  arrivals_checked_in: number;
  departures_expected: number;
  departures_checked_out: number;
  in_house: number;
  pending_holds: number;
  sellable_rooms: number;
  occupied_tonight: number;
  occupancy_percent: number;
}

export interface BoardBooking {
  id: number;
  confirmation_number: string;
  guest_name: string;
  is_vip: boolean;
  check_in_date: string;
  check_out_date: string;
}

export interface BoardRoom {
  room_id: number;
  room_number: string;
  floor_number: number;
  room_type: string;
  status: string;
  housekeeping_status?: string;
  in_house: BoardBooking | null;
  arriving: BoardBooking | null;
  departing_today: boolean;
}

export interface RoomType {
  id: number;
  name: string;
  slug: string;
  base_price: string;
  max_adults: number;
  max_children: number;
}

export interface Room {
  id: number;
  room_number: string;
  floor_number: number;
  status: string;
  room_type: number;
  room_type_detail: { name: string };
}

export interface Charge {
  id: number;
  category: string;
  description: string;
  quantity: string;
  net_amount: string;
  tax_amount: string;
  total_amount: string;
  service_date: string;
  posted_by: string | null;
  is_void: boolean;
  void_reason: string;
}

export interface FolioPayment {
  id: number;
  kind: 'PAYMENT' | 'REFUND';
  method: string;
  amount: string;
  tendered_currency: string;
  tendered_amount: string | null;
  reference: string;
  received_by: string | null;
  received_at: string;
  is_void: boolean;
}

export interface Folio {
  id: number;
  number: string;
  display_name: string;
  booking: number | null;
  confirmation_number: string | null;
  account: string | null;
  status: 'OPEN' | 'SETTLED' | 'TRANSFERRED';
  currency: string;
  charges_total: string;
  payments_total: string;
  balance: string;
  charges: Charge[];
  payments: FolioPayment[];
  invoices: { id: number; number: string; issued_at: string; total: string }[];
}

export interface StaffMember {
  id: number;
  email: string;
  first_name: string;
  last_name: string;
  phone: string;
  role: string;
  is_active: boolean;
  last_login: string | null;
  mfa_enabled?: boolean;
}

export interface AuditEntry {
  id: number;
  created_at: string;
  actor_email: string;
  action: string;
  target_type: string;
  target_repr: string;
  changes: Record<string, unknown>;
  ip_address: string | null;
}
