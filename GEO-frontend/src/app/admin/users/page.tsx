"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { adminApi } from "@/lib/admin-api";
import { useAuth } from "@/contexts/AuthContext";
import {
  Search,
  Filter,
  UserCheck,
  UserX,
  Shield,
  Layers,
  Sparkles,
  ChevronLeft,
  ChevronRight,
  RefreshCw,
  MoreHorizontal
} from "lucide-react";

interface AdminUser {
  id: string;
  email: string;
  role: string;
  is_suspended: boolean;
  subscription_plan: string | null;
  subscription_status: string | null;
  billing_cycle: string | null;
  credits_remaining: number;
  created_at: string;
}

export default function AdminUsersPage() {
  const { isSuperAdmin } = useAuth();
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [limit] = useState(15);
  const [search, setSearch] = useState("");
  const [planFilter, setPlanFilter] = useState("");
  const [roleFilter, setRoleFilter] = useState("");
  const [suspendedFilter, setSuspendedFilter] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Quick Action Modal State
  const [selectedUser, setSelectedUser] = useState<AdminUser | null>(null);
  const [actionType, setActionType] = useState<"plan" | "credits" | "role" | "suspend" | null>(null);
  const [modalInput, setModalInput] = useState<any>({});
  const [submitting, setSubmitting] = useState(false);

  const fetchUsers = async () => {
    try {
      setLoading(true);
      setError(null);
      const params = new URLSearchParams();
      params.set("page", page.toString());
      params.set("limit", limit.toString());
      if (search.trim()) params.set("search", search.trim());
      if (planFilter) params.set("plan", planFilter);
      if (roleFilter) params.set("role", roleFilter);
      if (suspendedFilter) params.set("is_suspended", suspendedFilter);

      const data = await adminApi.get<{ users: AdminUser[]; total: number }>(
        `/api/admin/users?${params.toString()}`
      );
      setUsers(data.users || []);
      setTotal(data.total || 0);
    } catch (err: any) {
      setError(err.message || "Failed to load users");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchUsers();
  }, [page, planFilter, roleFilter, suspendedFilter]);

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setPage(1);
    fetchUsers();
  };

  const handleQuickAction = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedUser || !actionType) return;
    try {
      setSubmitting(true);
      if (actionType === "plan") {
        await adminApi.post(`/api/admin/users/${selectedUser.id}/plan`, {
          plan_name: modalInput.plan_name || "Lite Plan",
          billing_cycle: modalInput.billing_cycle || "monthly",
          reason: modalInput.reason
        });
      } else if (actionType === "credits") {
        await adminApi.post(`/api/admin/users/${selectedUser.id}/credits`, {
          amount: parseInt(modalInput.amount || "10"),
          reason: modalInput.reason
        });
      } else if (actionType === "suspend") {
        await adminApi.post(`/api/admin/users/${selectedUser.id}/suspend`, {
          is_suspended: !selectedUser.is_suspended,
          reason: modalInput.reason
        });
      } else if (actionType === "role") {
        await adminApi.post(`/api/admin/users/${selectedUser.id}/role`, {
          role: modalInput.role || "admin",
          reason: modalInput.reason
        });
      }

      setActionType(null);
      setSelectedUser(null);
      setModalInput({});
      fetchUsers();
    } catch (err: any) {
      alert(`Action failed: ${err.message}`);
    } finally {
      setSubmitting(false);
    }
  };

  const totalPages = Math.ceil(total / limit) || 1;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-white">Users & Accounts</h1>
          <p className="text-sm text-slate-400">
            Manage subscriber roles, access bans, custom plans, and credit grants.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={fetchUsers}
            disabled={loading}
            className="inline-flex items-center gap-2 rounded-xl border border-slate-800 bg-slate-900 px-3 py-2 text-xs font-semibold text-slate-300 transition hover:bg-slate-800"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
            Refresh
          </button>
        </div>
      </div>

      {/* Filter Bar */}
      <div className="flex flex-col gap-3 rounded-2xl border border-slate-800 bg-slate-900/60 p-4 backdrop-blur-sm md:flex-row md:items-center md:justify-between">
        <form onSubmit={handleSearchSubmit} className="relative flex-1 max-w-md">
          <Search className="absolute left-3 top-2.5 h-4 w-4 text-slate-500" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search by email..."
            className="w-full rounded-xl border border-slate-800 bg-slate-950 py-2 pl-9 pr-4 text-xs text-white placeholder-slate-500 focus:border-indigo-500 focus:outline-none"
          />
        </form>

        <div className="flex flex-wrap items-center gap-2">
          {/* Plan Filter */}
          <select
            value={planFilter}
            onChange={(e) => {
              setPlanFilter(e.target.value);
              setPage(1);
            }}
            className="rounded-xl border border-slate-800 bg-slate-950 px-3 py-2 text-xs text-slate-300 focus:border-indigo-500 focus:outline-none"
          >
            <option value="">All Plans</option>
            <option value="free">Free</option>
            <option value="Lite Plan">Lite Plan</option>
            <option value="Growth Plan">Growth Plan</option>
            <option value="Pro Plan">Pro Plan</option>
            <option value="Enterprise">Enterprise</option>
          </select>

          {/* Role Filter */}
          <select
            value={roleFilter}
            onChange={(e) => {
              setRoleFilter(e.target.value);
              setPage(1);
            }}
            className="rounded-xl border border-slate-800 bg-slate-950 px-3 py-2 text-xs text-slate-300 focus:border-indigo-500 focus:outline-none"
          >
            <option value="">All Roles</option>
            <option value="user">User</option>
            <option value="admin">Admin</option>
            <option value="super_admin">Super Admin</option>
          </select>

          {/* Status Filter */}
          <select
            value={suspendedFilter}
            onChange={(e) => {
              setSuspendedFilter(e.target.value);
              setPage(1);
            }}
            className="rounded-xl border border-slate-800 bg-slate-950 px-3 py-2 text-xs text-slate-300 focus:border-indigo-500 focus:outline-none"
          >
            <option value="">All Statuses</option>
            <option value="false">Active Only</option>
            <option value="true">Suspended Only</option>
          </select>
        </div>
      </div>

      {error && (
        <div className="rounded-xl border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-300">
          {error}
        </div>
      )}

      {/* Users Table */}
      <div className="overflow-hidden rounded-2xl border border-slate-800 bg-slate-900/60 backdrop-blur-sm">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="border-b border-slate-800 bg-slate-950/60 text-slate-400">
              <tr>
                <th className="px-4 py-3.5 font-medium">User Email</th>
                <th className="px-4 py-3.5 font-medium">Role</th>
                <th className="px-4 py-3.5 font-medium">Plan</th>
                <th className="px-4 py-3.5 font-medium">Status</th>
                <th className="px-4 py-3.5 font-medium">Credits</th>
                <th className="px-4 py-3.5 font-medium">Created</th>
                <th className="px-4 py-3.5 text-right font-medium">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/80">
              {loading ? (
                <tr>
                  <td colSpan={7} className="py-12 text-center text-slate-500">
                    Loading users...
                  </td>
                </tr>
              ) : users.length === 0 ? (
                <tr>
                  <td colSpan={7} className="py-12 text-center text-slate-500">
                    No users matching criteria.
                  </td>
                </tr>
              ) : (
                users.map((user) => (
                  <tr key={user.id} className="hover:bg-slate-800/30 transition">
                    <td className="px-4 py-3 font-medium text-white">
                      <Link
                        href={`/admin/users/${user.id}`}
                        className="hover:text-indigo-400 hover:underline"
                      >
                        {user.email}
                      </Link>
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`inline-flex items-center gap-1 rounded px-2 py-0.5 text-[11px] font-medium border ${
                          user.role === "super_admin"
                            ? "border-amber-500/30 bg-amber-500/10 text-amber-300"
                            : user.role === "admin"
                            ? "border-indigo-500/30 bg-indigo-500/10 text-indigo-300"
                            : "border-slate-700 bg-slate-800/60 text-slate-400"
                        }`}
                      >
                        {user.role}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <span className="capitalize font-medium text-slate-300">
                        {user.subscription_plan || "free"}
                      </span>
                      {user.billing_cycle && (
                        <span className="text-[10px] text-slate-500 ml-1">
                          ({user.billing_cycle})
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      {user.is_suspended ? (
                        <span className="inline-flex items-center gap-1 rounded bg-red-500/10 px-2 py-0.5 text-[11px] font-medium text-red-400 border border-red-500/20">
                          Suspended
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 rounded bg-emerald-500/10 px-2 py-0.5 text-[11px] font-medium text-emerald-400 border border-emerald-500/20">
                          Active
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3 font-mono text-slate-300">
                      {user.credits_remaining ?? 0}
                    </td>
                    <td className="px-4 py-3 text-slate-400">
                      {new Date(user.created_at).toLocaleDateString()}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <div className="flex items-center justify-end gap-1.5">
                        {/* Grant Plan Button */}
                        <button
                          onClick={() => {
                            setSelectedUser(user);
                            setActionType("plan");
                            setModalInput({ plan_name: user.subscription_plan || "Lite Plan" });
                          }}
                          className="rounded-lg border border-slate-800 bg-slate-900 px-2.5 py-1 text-[11px] font-medium text-slate-300 hover:border-slate-700 hover:text-white transition"
                        >
                          Plan
                        </button>

                        {/* Credits Button */}
                        <button
                          onClick={() => {
                            setSelectedUser(user);
                            setActionType("credits");
                            setModalInput({ amount: "10" });
                          }}
                          className="rounded-lg border border-slate-800 bg-slate-900 px-2.5 py-1 text-[11px] font-medium text-slate-300 hover:border-slate-700 hover:text-white transition"
                        >
                          +Credits
                        </button>

                        {/* Suspend Button */}
                        <button
                          onClick={() => {
                            setSelectedUser(user);
                            setActionType("suspend");
                          }}
                          className={`rounded-lg px-2.5 py-1 text-[11px] font-medium border transition ${
                            user.is_suspended
                              ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-400 hover:bg-emerald-500/20"
                              : "border-red-500/30 bg-red-500/10 text-red-400 hover:bg-red-500/20"
                          }`}
                        >
                          {user.is_suspended ? "Unsuspend" : "Suspend"}
                        </button>

                        {/* Super Admin Role Change */}
                        {isSuperAdmin && (
                          <button
                            onClick={() => {
                              setSelectedUser(user);
                              setActionType("role");
                              setModalInput({ role: user.role === "admin" ? "user" : "admin" });
                            }}
                            className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-2.5 py-1 text-[11px] font-medium text-amber-300 hover:bg-amber-500/20 transition"
                          >
                            Role
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination Bar */}
        <div className="flex items-center justify-between border-t border-slate-800 px-4 py-3 text-xs text-slate-400">
          <div>
            Showing {users.length > 0 ? (page - 1) * limit + 1 : 0} to{" "}
            {Math.min(page * limit, total)} of {total} users
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page <= 1 || loading}
              className="rounded-lg border border-slate-800 bg-slate-900 p-1.5 hover:bg-slate-800 disabled:opacity-40"
            >
              <ChevronLeft className="h-4 w-4" />
            </button>
            <span className="font-medium text-slate-300">
              Page {page} of {totalPages}
            </span>
            <button
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              disabled={page >= totalPages || loading}
              className="rounded-lg border border-slate-800 bg-slate-900 p-1.5 hover:bg-slate-800 disabled:opacity-40"
            >
              <ChevronRight className="h-4 w-4" />
            </button>
          </div>
        </div>
      </div>

      {/* ── Action Modal ───────────────────────────────────────────────────── */}
      {actionType && selectedUser && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm">
          <div className="w-full max-w-md rounded-2xl border border-slate-800 bg-slate-900 p-6 shadow-2xl">
            <h3 className="text-base font-bold text-white">
              {actionType === "plan" && `Update Plan for ${selectedUser.email}`}
              {actionType === "credits" && `Add Credits for ${selectedUser.email}`}
              {actionType === "suspend" &&
                `${selectedUser.is_suspended ? "Unsuspend" : "Suspend"} ${selectedUser.email}`}
              {actionType === "role" && `Modify Role for ${selectedUser.email}`}
            </h3>

            <form onSubmit={handleQuickAction} className="mt-4 space-y-4">
              {actionType === "plan" && (
                <>
                  <div>
                    <label className="text-xs text-slate-400">Target Plan</label>
                    <select
                      value={modalInput.plan_name || "Lite Plan"}
                      onChange={(e) => setModalInput({ ...modalInput, plan_name: e.target.value })}
                      className="mt-1 w-full rounded-xl border border-slate-800 bg-slate-950 p-2.5 text-xs text-white"
                    >
                      <option value="free">Free</option>
                      <option value="Lite Plan">Lite Plan</option>
                      <option value="Growth Plan">Growth Plan</option>
                      <option value="Pro Plan">Pro Plan</option>
                      <option value="Enterprise">Enterprise</option>
                    </select>
                  </div>
                  <div>
                    <label className="text-xs text-slate-400">Billing Cycle</label>
                    <select
                      value={modalInput.billing_cycle || "monthly"}
                      onChange={(e) => setModalInput({ ...modalInput, billing_cycle: e.target.value })}
                      className="mt-1 w-full rounded-xl border border-slate-800 bg-slate-950 p-2.5 text-xs text-white"
                    >
                      <option value="monthly">Monthly (+30 days)</option>
                      <option value="yearly">Yearly (+365 days)</option>
                    </select>
                  </div>
                </>
              )}

              {actionType === "credits" && (
                <div>
                  <label className="text-xs text-slate-400">Additional Credits Count</label>
                  <input
                    type="number"
                    min="1"
                    value={modalInput.amount || "10"}
                    onChange={(e) => setModalInput({ ...modalInput, amount: e.target.value })}
                    className="mt-1 w-full rounded-xl border border-slate-800 bg-slate-950 p-2.5 text-xs text-white"
                  />
                </div>
              )}

              {actionType === "role" && (
                <div>
                  <label className="text-xs text-slate-400">Assign Role</label>
                  <select
                    value={modalInput.role || "admin"}
                    onChange={(e) => setModalInput({ ...modalInput, role: e.target.value })}
                    className="mt-1 w-full rounded-xl border border-slate-800 bg-slate-950 p-2.5 text-xs text-white"
                  >
                    <option value="user">User</option>
                    <option value="admin">Admin</option>
                    <option value="super_admin">Super Admin</option>
                  </select>
                </div>
              )}

              {actionType === "suspend" && (
                <p className="text-xs text-slate-300">
                  {selectedUser.is_suspended
                    ? "Unsuspending will restore this user's ability to run analyses and access the dashboard immediately."
                    : "Suspension immediately denies this user access to all API endpoints and the dashboard."}
                </p>
              )}

              <div>
                <label className="text-xs text-slate-400">Audit Reason / Note</label>
                <input
                  type="text"
                  placeholder="e.g. Customer requested upgrade, Chargeback dispute, Support credit grant"
                  value={modalInput.reason || ""}
                  onChange={(e) => setModalInput({ ...modalInput, reason: e.target.value })}
                  className="mt-1 w-full rounded-xl border border-slate-800 bg-slate-950 p-2.5 text-xs text-white"
                />
              </div>

              <div className="mt-6 flex justify-end gap-2">
                <button
                  type="button"
                  onClick={() => setActionType(null)}
                  className="rounded-xl border border-slate-800 px-4 py-2 text-xs font-semibold text-slate-400 hover:bg-slate-800"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={submitting}
                  className="rounded-xl bg-indigo-600 px-4 py-2 text-xs font-semibold text-white hover:bg-indigo-500 disabled:opacity-50"
                >
                  {submitting ? "Saving..." : "Confirm & Apply"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
