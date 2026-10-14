import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';

import { api, post, refreshSession, setAccessToken, setSessionExpiredHandler } from '../api/client';
import type { Capability, User } from '../api/types';

interface AuthState {
  user: User | null;
  loading: boolean;
  /** Returns an MFA ticket when a second step is needed, otherwise null. */
  login: (email: string, password: string) => Promise<string | null>;
  completeMfa: (ticket: string, code: string, recovery?: boolean) => Promise<void>;
  refreshUser: () => Promise<void>;
  logout: () => Promise<void>;
  can: (capability: Capability) => boolean;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setSessionExpiredHandler(() => setUser(null));
    // Restore the session from the refresh cookie after a page reload
    refreshSession()
      .then((ok) => (ok ? api<User>('auth/me/').then(setUser) : undefined))
      .catch(() => setUser(null))
      .finally(() => setLoading(false));
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const data = await post<{ access?: string; user?: User; mfa_required?: boolean; mfa_ticket?: string }>(
      'auth/login/', { email, password });
    if (data.mfa_required) return data.mfa_ticket ?? null;
    setAccessToken(data.access ?? null);
    setUser(data.user ?? null);
    return null;
  }, []);

  const completeMfa = useCallback(async (ticket: string, code: string, recovery = false) => {
    const data = await post<{ access: string; user: User }>('auth/login/mfa/',
      recovery ? { mfa_ticket: ticket, recovery_code: code } : { mfa_ticket: ticket, code });
    setAccessToken(data.access);
    setUser(data.user);
  }, []);

  const refreshUser = useCallback(async () => setUser(await api<User>('auth/me/')), []);

  const logout = useCallback(async () => {
    try {
      await post('auth/logout/');
    } finally {
      setAccessToken(null);
      setUser(null);
    }
  }, []);

  const value = useMemo<AuthState>(() => ({
    user,
    loading,
    login,
    completeMfa,
    refreshUser,
    logout,
    can: (capability) => !!user?.capabilities.includes(capability),
  }), [user, loading, login, completeMfa, refreshUser, logout]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error('useAuth must be used inside AuthProvider');
  return context;
}
