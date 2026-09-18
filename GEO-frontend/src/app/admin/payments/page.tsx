"use client";

import React, { useEffect, useState } from "react";
import { adminApi } from "@/lib/admin-api";
import { useAuth } from "@/contexts/AuthContext";
import {
  Search,
  CreditCard,
  RotateCcw,
  AlertTriangle,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  RefreshCw
} from "lucide-react";

interface PaymentTransaction {
  id: string;
  user_id: string;
  user_email: string;
  razorpay_order_id: string;
  razorpay_payment_id: string;
  plan_name: string;
  billing_cycle: string;
  status: string;
  refund_id?: string;
  subscription_end: string;
  created_at: string;
}

export default function AdminPaymentsPage() {
  const { isSuperAdmin } = useAuth();
  const [payments, setPayments] = useState<PaymentTransaction[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [limit] = useState(15);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Refund Modal State
  const [refundTarget, setRefundTarget] = useState<PaymentTransaction | null>(null);
  const [refundReason, setRefundReason] = useState("");
  const [refunding, setRefunding] = useState(false);

  const fetchPayments = async () => {
    try {
      setLoading(true);
      setError(null);
      const params = new URLSearchParams();
      params.set("page", page.toString());
      params.set("limit", limit.toString());
      if (search.trim()) params.set("search", search.trim());
      if (statusFilter) params.set("status", statusFilter);

      const data = await adminApi.get<{ payments: PaymentTransaction[]; total: number }>(
        `/api/admin/payments?${params.toString()}`
      );
      setPayments(data.payments || []);
      setTotal(data.total || 0);
    } catch (err: any) {
      setError(err.message || "Failed to load payments");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchPayments();
  }, [page, statusFilter]);

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setPage(1);
    fetchPayments();
  };

  const handleRefundSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!refundTarget) return;

    try {
      setRefunding(true);
      await adminApi.post(`/api/admin/payments/${refundTarget.razorpay_payment_id}/refund`, {
        reason: refundReason.trim() || "Admin initiated refund"
      });

      alert(`Refund initiated successfully for ${refundTarget.razorpay_payment_id}`);
      setRefundTarget(null);
      setRefundReason("");
      fetchPayments();
    } catch (err: any) {
      alert(`Refund failed: ${err.message}`);
    } finally {
      setRefunding(false);
    }
  };

  const totalPages = Math.ceil(total / limit) || 1;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-white">Payments & Refunds</h1>
          <p className="text-sm text-slate-400">
            Immutable audit ledger of all Razorpay transactions, activations, and issued refunds.
          </p>
        </div>
        <button
          onClick={fetchPayments}
          disabled={loading}
          className="inline-flex items-center gap-2 rounded-xl border border-slate-800 bg-slate-900 px-3 py-2 text-xs font-semibold text-slate-300 transition hover:bg-slate-800"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
          Refresh
        </button>
      </div>

      {/* Filter Bar */}
      <div className="flex flex-col gap-3 rounded-2xl border border-slate-800 bg-slate-900/60 p-4 backdrop-blur-sm md:flex-row md:items-center md:justify-between">
        <form onSubmit={handleSearchSubmit} className="relative flex-1 max-w-md">
          <Search className="absolute left-3 top-2.5 h-4 w-4 text-slate-500" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search by email, payment ID, order ID..."
            className="w-full rounded-xl border border-slate-800 bg-slate-950 py-2 pl-9 pr-4 text-xs text-white placeholder-slate-500 focus:border-indigo-500 focus:outline-none"
          />
        </form>

        <select
          value={statusFilter}
          onChange={(e) => {
            setStatusFilter(e.target.value);
            setPage(1);
          }}
          className="rounded-xl border border-slate-800 bg-slate-950 px-3 py-2 text-xs text-slate-300 focus:border-indigo-500 focus:outline-none"
        >
          <option value="">All Statuses</option>
          <option value="verified">Verified</option>
          <option value="refunded">Refunded</option>
        </select>
      </div>

      {error && (
        <div className="rounded-xl border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-300">
          {error}
        </div>
      )}

      {/* Table */}
      <div className="overflow-hidden rounded-2xl border border-slate-800 bg-slate-900/60 backdrop-blur-sm">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="border-b border-slate-800 bg-slate-950/60 text-slate-400">
              <tr>
                <th className="px-4 py-3.5 font-medium">Date</th>
                <th className="px-4 py-3.5 font-medium">Customer Email</th>
                <th className="px-4 py-3.5 font-medium">Plan</th>
                <th className="px-4 py-3.5 font-medium">Cycle</th>
                <th className="px-4 py-3.5 font-medium">Payment ID</th>
                <th className="px-4 py-3.5 font-medium">Status</th>
                <th className="px-4 py-3.5 text-right font-medium">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/80">
              {loading ? (
                <tr>
                  <td colSpan={7} className="py-12 text-center text-slate-500">
                    Loading transactions...
                  </td>
                </tr>
              ) : payments.length === 0 ? (
                <tr>
                  <td colSpan={7} className="py-12 text-center text-slate-500">
                    No transactions found.
                  </td>
                </tr>
              ) : (
                payments.map((p) => (
                  <tr key={p.id} className="hover:bg-slate-800/30 transition">
                    <td className="px-4 py-3 text-slate-400">{new Date(p.created_at).toLocaleDateString()}</td>
                    <td className="px-4 py-3 font-medium text-white">{p.user_email}</td>
                    <td className="px-4 py-3 capitalize text-slate-300">{p.plan_name}</td>
                    <td className="px-4 py-3 capitalize text-slate-400">{p.billing_cycle}</td>
                    <td className="px-4 py-3 font-mono text-[11px] text-slate-300">
                      {p.razorpay_payment_id}
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`inline-flex items-center gap-1 rounded px-2 py-0.5 text-[10px] font-medium border ${
                          p.status === "verified"
                            ? "border-emerald-500/20 bg-emerald-500/10 text-emerald-400"
                            : "border-amber-500/20 bg-amber-500/10 text-amber-300"
                        }`}
                      >
                        {p.status}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right">
                      {p.status !== "refunded" && isSuperAdmin ? (
                        <button
                          onClick={() => setRefundTarget(p)}
                          className="inline-flex items-center gap-1 rounded-lg border border-red-500/30 bg-red-500/10 px-2.5 py-1 text-[11px] font-medium text-red-400 hover:bg-red-500/20 transition"
                        >
                          <RotateCcw className="h-3 w-3" />
                          Refund
                        </button>
                      ) : p.status === "refunded" ? (
                        <span className="text-[11px] text-slate-500">Refunded</span>
                      ) : (
                        <span className="text-[11px] text-slate-500">Super Admin Only</span>
                      )}
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
            Showing {payments.length > 0 ? (page - 1) * limit + 1 : 0} to{" "}
            {Math.min(page * limit, total)} of {total} transactions
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

      {/* ── Refund Modal ───────────────────────────────────────────────────── */}
      {refundTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm">
          <div className="w-full max-w-md rounded-2xl border border-red-500/30 bg-slate-900 p-6 shadow-2xl">
            <div className="flex items-center gap-2 text-red-400">
              <AlertTriangle className="h-5 w-5" />
              <h3 className="text-base font-bold text-white">Confirm Payment Refund</h3>
            </div>
            <p className="mt-2 text-xs text-slate-400">
              This will issue an immediate refund via Razorpay for transaction{" "}
              <span className="font-mono text-slate-200">{refundTarget.razorpay_payment_id}</span> ({refundTarget.user_email}).
            </p>

            <form onSubmit={handleRefundSubmit} className="mt-4 space-y-4">
              <div>
                <label className="text-xs text-slate-400">Refund Reason (Audited)</label>
                <input
                  type="text"
                  required
                  placeholder="e.g. Customer cancelled within 24h, accidental double-charge"
                  value={refundReason}
                  onChange={(e) => setRefundReason(e.target.value)}
                  className="mt-1 w-full rounded-xl border border-slate-800 bg-slate-950 p-2.5 text-xs text-white placeholder-slate-500 focus:border-red-500 focus:outline-none"
                />
              </div>

              <div className="mt-6 flex justify-end gap-2">
                <button
                  type="button"
                  onClick={() => setRefundTarget(null)}
                  className="rounded-xl border border-slate-800 px-4 py-2 text-xs font-semibold text-slate-400 hover:bg-slate-800"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={refunding}
                  className="rounded-xl bg-red-600 px-4 py-2 text-xs font-semibold text-white hover:bg-red-500 disabled:opacity-50"
                >
                  {refunding ? "Processing Refund..." : "Issue Full Refund"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
