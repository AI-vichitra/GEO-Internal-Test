"use client";

import React, { createContext, useContext, useState, useEffect, useCallback, ReactNode } from "react";

import { setAuthToken, getAuthToken } from "@/lib/queryClient";

export { getAuthToken };

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "https://api.optimiseurbrand.tech";

// ─── Types ────────────────────────────────────────────────────────────────────

interface SubscriptionStatus {
  is_active: boolean;
  subscription_plan: string | null;
  subscription_status: string | null;
  subscription_start: string | null;
  subscription_end: string | null;
  billing_cycle: string | null;
}

interface PlanLimits {
  max_projects: number;
  max_competitors: number;
  max_prompts_per_project: number;
}

const DEFAULT_SUBSCRIPTION: SubscriptionStatus = {
  is_active: true,
  subscription_plan: "free",
  subscription_status: "active",
  subscription_start: null,
  subscription_end: null,
  billing_cycle: null,
};

const DEFAULT_PLAN_LIMITS: PlanLimits = {
  max_projects: 1,
  max_competitors: 10,
  max_prompts_per_project: 5,
};

interface AuthContextType {
  isAuthenticated: boolean;
  userId: string | null;
  email: string | null;
  role: string | null;
  isAdmin: boolean;
  isSuperAdmin: boolean;
  token: string | null;
  subscription: SubscriptionStatus;
  planLimits: PlanLimits;
  isLoading: boolean;
  login: (token: string, userId: string, email: string, subscription?: SubscriptionStatus, role?: string, planLimits?: PlanLimits) => void;
  logout: () => void;
  refreshUser: () => Promise<void>;
}

// ─── Context ──────────────────────────────────────────────────────────────────

const AuthContext = createContext<AuthContextType | undefined>(undefined);

// ─── Provider ─────────────────────────────────────────────────────────────────

export function AuthProvider({ children }: { children: ReactNode }) {
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [userId, setUserId] = useState<string | null>(null);
  const [email, setEmail] = useState<string | null>(null);
  const [role, setRole] = useState<string | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [subscription, setSubscription] = useState<SubscriptionStatus>(DEFAULT_SUBSCRIPTION);
  const [planLimits, setPlanLimits] = useState<PlanLimits>(DEFAULT_PLAN_LIMITS);
  const [isLoading, setIsLoading] = useState(true);

  const isAdmin = role === "admin" || role === "super_admin";
  const isSuperAdmin = role === "super_admin";

  // ── Internal helper: fetch both /api/auth/me AND /api/payments/subscription-status concurrently ──
  const fetchUserProfile = useCallback(async (tokenOverride?: string) => {
    try {
      const activeToken = tokenOverride || getAuthToken();
      const headers: Record<string, string> = activeToken ? { Authorization: `Bearer ${activeToken}` } : {};
      const [meRes, subRes] = await Promise.all([
        fetch(`${API_BASE_URL}/api/auth/me`, { headers, credentials: "include" }),
        fetch(`${API_BASE_URL}/api/payments/subscription-status`, { headers, credentials: "include" }),
      ]);

      if (!meRes.ok) throw new Error("Session invalid or expired");

      const meData = await meRes.json();
      if (meData?.token) {
        setToken(meData.token);
        setAuthToken(meData.token);
      }
      if (meData?.user) {
        setUserId(meData.user.id);
        setEmail(meData.user.email);
        setRole(meData.user.role || "user");
        setIsAuthenticated(true);
      }

      const subData = subRes.ok ? await subRes.json() : null;
      const subscriptionData: SubscriptionStatus =
        subData?.subscription ?? DEFAULT_SUBSCRIPTION;
      const limitsData: PlanLimits =
        subData?.plan_limits ?? DEFAULT_PLAN_LIMITS;

      setSubscription(subscriptionData);
      setPlanLimits(limitsData);
    } catch (err) {
      // Clear in-memory token on auth failure
      setToken(null);
      setAuthToken(null);
      setUserId(null);
      setEmail(null);
      setRole(null);
      setIsAuthenticated(false);
      setSubscription(DEFAULT_SUBSCRIPTION);
      setPlanLimits(DEFAULT_PLAN_LIMITS);
    }
  }, []);

  // ── Restore session on mount via HttpOnly cookie (or in-memory token) ────────────
  useEffect(() => {
    fetchUserProfile().finally(() => setIsLoading(false));
  }, [fetchUserProfile]);

  // ── Refresh plan limits every 2 minutes while authenticated ──────────────
  // This ensures admin CMS changes propagate without requiring logout.
  useEffect(() => {
    if (!isAuthenticated) return;

    const interval = setInterval(() => {
      const activeToken = getAuthToken();
      const headers: Record<string, string> = activeToken ? { Authorization: `Bearer ${activeToken}` } : {};
      fetch(`${API_BASE_URL}/api/payments/subscription-status`, {
        headers,
        credentials: "include",
      })
        .then((r) => (r.ok ? r.json() : null))
        .then((data) => {
          if (data?.plan_limits) setPlanLimits(data.plan_limits);
          if (data?.subscription) setSubscription(data.subscription);
        })
        .catch(() => {/* silent — user still logged in */});
    }, 2 * 60 * 1000); // every 2 minutes

    return () => clearInterval(interval);
  }, [isAuthenticated]);

  // ── login: called right after successful auth response ────────────────────
  const login = (
    newToken: string,
    newUserId: string,
    newEmail: string,
    newSubscription: SubscriptionStatus = DEFAULT_SUBSCRIPTION,
    newRole: string = "user",
    newPlanLimits?: PlanLimits
  ) => {
    setToken(newToken);
    setAuthToken(newToken);
    setUserId(newUserId);
    setEmail(newEmail);
    setRole(newRole);
    setSubscription(newSubscription);
    if (newPlanLimits) {
      setPlanLimits(newPlanLimits);
    }
    setIsAuthenticated(true);
    // Background fetch to ensure full sync with latest DB state
    fetchUserProfile(newToken);
  };

  // ── logout: calls backend to clear HttpOnly cookie and clears memory ───────
  const logout = () => {
    fetch(`${API_BASE_URL}/api/auth/logout`, {
      method: "POST",
      credentials: "include",
    }).catch(() => {});

    setToken(null);
    setAuthToken(null);
    setUserId(null);
    setEmail(null);
    setRole(null);
    setSubscription(DEFAULT_SUBSCRIPTION);
    setPlanLimits(DEFAULT_PLAN_LIMITS);
    setIsAuthenticated(false);
  };

  // ── refreshUser: called by pricing page after payment to force-sync state ──
  const refreshUser = useCallback(async () => {
    await fetchUserProfile();
  }, [fetchUserProfile]);

  return (
    <AuthContext.Provider
      value={{
        isAuthenticated,
        userId,
        email,
        role,
        isAdmin,
        isSuperAdmin,
        token,
        subscription,
        planLimits,
        isLoading,
        login,
        logout,
        refreshUser,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

// ─── Hook ─────────────────────────────────────────────────────────────────────

export function useAuth() {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error("useAuth must be used within AuthProvider");
  }
  return context;
}
