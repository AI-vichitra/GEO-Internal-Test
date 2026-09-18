"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { adminApi } from "@/lib/admin-api";
import { useAuth } from "@/contexts/AuthContext";
import {
  ArrowLeft,
  Shield,
  Layers,
  Sparkles,
  Calendar,
  CreditCard,
  FolderGit2,
  Activity,
  UserX,
  UserCheck,
  CheckCircle,
  AlertTriangle
} from "lucide-react";

export default function AdminUserDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { isSuperAdmin } = useAuth();

  const [user, setUser] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchUserDetail = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await adminApi.get(`/api/admin/users/${id}`);
      setUser(data);
    } catch (err: any) {
      setError(err.message || "Failed to load user detail");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (id) fetchUserDetail();
  }, [id]);

  if (loading) {
    return (
      <div className="flex h-96 items-center justify-center">
        <div className="flex flex-col items-center gap-2">
          <div className="h-8 w-8 animate-spin rounded-full border-4 border-indigo-500 border-t-transparent" />
          <p className="text-xs text-slate-400">Loading user profile...</p>
        </div>
      </div>
    );
  }

  if (error || !user) {
    return (
      <div className="space-y-4">
        <Link href="/admin/users" className="inline-flex items-center gap-2 text-xs text-slate-400 hover:text-white">
          <ArrowLeft className="h-4 w-4" /> Back to users
        </Link>
        <div className="rounded-2xl border border-red-500/30 bg-red-500/10 p-6 text-red-300">
          {error || "User not found"}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-8">
      {/* Back Button & Header */}
      <div className="space-y-3">
        <Link
          href="/admin/users"
          className="inline-flex items-center gap-1.5 text-xs text-slate-400 transition hover:text-white"
        >
          <ArrowLeft className="h-4 w-4" />
          Back to all users
        </Link>
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <div className="flex items-center gap-3">
              <h1 className="text-2xl font-bold tracking-tight text-white">{user.email}</h1>
              <span
                className={`rounded px-2 py-0.5 text-xs font-semibold border ${
                  user.role === "super_admin"
                    ? "border-amber-500/30 bg-amber-500/10 text-amber-300"
                    : user.role === "admin"
                    ? "border-indigo-500/30 bg-indigo-500/10 text-indigo-300"
                    : "border-slate-700 bg-slate-800 text-slate-400"
                }`}
              >
                {user.role}
              </span>
              {user.is_suspended && (
                <span className="rounded bg-red-500/10 px-2 py-0.5 text-xs font-medium text-red-400 border border-red-500/20">
                  Suspended
                </span>
              )}
            </div>
            <p className="font-mono text-xs text-slate-500 mt-1">UUID: {user.id}</p>
          </div>
        </div>
      </div>

      {/* Grid of details */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        {/* Account & Activity Card */}
        <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-6 backdrop-blur-sm space-y-4">
          <h2 className="text-sm font-semibold text-white flex items-center gap-2">
            <Activity className="h-4 w-4 text-indigo-400" />
            Account Overview
          </h2>
          <div className="space-y-3 text-xs">
            <div className="flex justify-between border-b border-slate-800 pb-2">
              <span className="text-slate-400">Account Status</span>
              <span className={user.is_suspended ? "text-red-400 font-medium" : "text-emerald-400 font-medium"}>
                {user.is_suspended ? "Suspended" : "Active"}
              </span>
            </div>
            <div className="flex justify-between border-b border-slate-800 pb-2">
              <span className="text-slate-400">Available Credits</span>
              <span className="font-mono text-white font-semibold">{user.credits_remaining ?? 0}</span>
            </div>
            <div className="flex justify-between border-b border-slate-800 pb-2">
              <span className="text-slate-400">Total Credits Granted</span>
              <span className="font-mono text-slate-300">{user.credits_total ?? 0}</span>
            </div>
            <div className="flex justify-between border-b border-slate-800 pb-2">
              <span className="text-slate-400">Analysis Sessions Run</span>
              <span className="font-mono text-slate-300">{user.total_sessions}</span>
            </div>
            <div className="flex justify-between border-b border-slate-800 pb-2">
              <span className="text-slate-400">Monitored Projects</span>
              <span className="font-mono text-slate-300">{user.total_projects}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-400">Registered Date</span>
              <span className="text-slate-300">{new Date(user.created_at).toLocaleString()}</span>
            </div>
          </div>
        </div>

        {/* Subscription Plan Card */}
        <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-6 backdrop-blur-sm space-y-4">
          <h2 className="text-sm font-semibold text-white flex items-center gap-2">
            <Layers className="h-4 w-4 text-emerald-400" />
            Subscription Details
          </h2>
          <div className="space-y-3 text-xs">
            <div className="flex justify-between border-b border-slate-800 pb-2">
              <span className="text-slate-400">Current Plan</span>
              <span className="capitalize font-semibold text-indigo-400">
                {user.subscription_plan || "Free"}
              </span>
            </div>
            <div className="flex justify-between border-b border-slate-800 pb-2">
              <span className="text-slate-400">Billing Cycle</span>
              <span className="capitalize text-slate-300">{user.billing_cycle || "N/A"}</span>
            </div>
            <div className="flex justify-between border-b border-slate-800 pb-2">
              <span className="text-slate-400">Subscription Status</span>
              <span className="capitalize text-slate-300">{user.subscription_status || "Inactive"}</span>
            </div>
            <div className="flex justify-between border-b border-slate-800 pb-2">
              <span className="text-slate-400">Start Date</span>
              <span className="text-slate-300">
                {user.subscription_start ? new Date(user.subscription_start).toLocaleDateString() : "N/A"}
              </span>
            </div>
            <div className="flex justify-between border-b border-slate-800 pb-2">
              <span className="text-slate-400">End / Renews</span>
              <span className="text-slate-300">
                {user.subscription_end ? new Date(user.subscription_end).toLocaleDateString() : "N/A"}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-400">Razorpay Payment ID</span>
              <span className="font-mono text-[11px] text-slate-400 truncate max-w-[140px]">
                {user.razorpay_payment_id || "None"}
              </span>
            </div>
          </div>
        </div>

        {/* Security & Access Card */}
        <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-6 backdrop-blur-sm space-y-4">
          <h2 className="text-sm font-semibold text-white flex items-center gap-2">
            <Shield className="h-4 w-4 text-amber-400" />
            Security & Roles
          </h2>
          <div className="space-y-3 text-xs">
            <div className="flex justify-between border-b border-slate-800 pb-2">
              <span className="text-slate-400">Assigned Role</span>
              <span className="font-semibold capitalize text-amber-300">{user.role}</span>
            </div>
            <div className="flex justify-between border-b border-slate-800 pb-2">
              <span className="text-slate-400">Email Verified</span>
              <span className="text-slate-300">{user.is_verified ? "Yes" : "No"}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-400">Last Updated</span>
              <span className="text-slate-300">
                {user.updated_at ? new Date(user.updated_at).toLocaleString() : "N/A"}
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* Recent Payments Section */}
      <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-6 backdrop-blur-sm space-y-4">
        <h2 className="text-base font-semibold text-white flex items-center gap-2">
          <CreditCard className="h-4 w-4 text-indigo-400" />
          Recent Invoices & Transactions
        </h2>
        {user.recent_payments?.length === 0 ? (
          <p className="text-xs text-slate-500 py-4 text-center">No payment transactions found for this user.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="border-b border-slate-800 bg-slate-950/40 text-slate-400">
                <tr>
                  <th className="py-2.5 px-3">Order ID</th>
                  <th className="py-2.5 px-3">Payment ID</th>
                  <th className="py-2.5 px-3">Plan</th>
                  <th className="py-2.5 px-3">Cycle</th>
                  <th className="py-2.5 px-3">Status</th>
                  <th className="py-2.5 px-3">Date</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60">
                {user.recent_payments.map((p: any) => (
                  <tr key={p.id}>
                    <td className="py-2.5 px-3 font-mono text-slate-300">{p.razorpay_order_id}</td>
                    <td className="py-2.5 px-3 font-mono text-slate-300">{p.razorpay_payment_id}</td>
                    <td className="py-2.5 px-3 capitalize text-white">{p.plan_name}</td>
                    <td className="py-2.5 px-3 capitalize text-slate-400">{p.billing_cycle}</td>
                    <td className="py-2.5 px-3">
                      <span className="rounded bg-emerald-500/10 px-2 py-0.5 text-[10px] font-medium text-emerald-400 border border-emerald-500/20">
                        {p.status}
                      </span>
                    </td>
                    <td className="py-2.5 px-3 text-slate-400">{new Date(p.created_at).toLocaleDateString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
