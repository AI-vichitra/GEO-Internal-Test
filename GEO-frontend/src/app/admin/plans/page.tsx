"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { adminApi } from "@/lib/admin-api";
import { Layers, Sparkles, CheckCircle2, UserPlus, RefreshCw, AlertCircle, Settings } from "lucide-react";

export default function AdminPlansPage() {
  const [stats, setStats] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  // Quick Grant Form
  const [email, setEmail] = useState("");
  const [plan, setPlan] = useState("Lite Plan");
  const [cycle, setCycle] = useState("monthly");
  const [durationDays, setDurationDays] = useState("30");
  const [reason, setReason] = useState("");
  const [granting, setGranting] = useState(false);
  const [feedback, setFeedback] = useState<{ type: "success" | "error"; message: string } | null>(null);

  const fetchPlanStats = async () => {
    try {
      setLoading(true);
      const data = await adminApi.get("/api/admin/stats");
      setStats(data);
    } catch (err: any) {
      console.error("Failed to load plan stats:", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchPlanStats();
  }, []);

  const handleGrantPlan = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email.trim()) return;

    try {
      setGranting(true);
      setFeedback(null);

      // 1. Look up user by email
      const searchRes = await adminApi.get<{ users: any[] }>(`/api/admin/users?search=${encodeURIComponent(email.trim())}`);
      const matched = searchRes.users.find((u) => u.email.toLowerCase() === email.trim().toLowerCase());

      if (!matched) {
        throw new Error(`No user found with email: ${email}`);
      }

      // 2. Apply plan
      await adminApi.post(`/api/admin/users/${matched.id}/plan`, {
        plan_name: plan,
        billing_cycle: cycle,
        duration_days: parseInt(durationDays) || 30,
        reason: reason.trim() || "Manual plan grant from Admin Portal"
      });

      setFeedback({
        type: "success",
        message: `Successfully granted ${plan} (${cycle}) to ${email}!`
      });
      setEmail("");
      setReason("");
      fetchPlanStats();
    } catch (err: any) {
      setFeedback({ type: "error", message: err.message || "Failed to grant plan" });
    } finally {
      setGranting(false);
    }
  };

  const planTiers = [
    { name: "Lite Plan", price: "₹2,400 / mo", alias: "lite plan" },
    { name: "Growth Plan", price: "₹6,500 / mo", alias: "growth plan" },
    { name: "Pro Plan", price: "₹11,500 / mo", alias: "pro plan" },
    { name: "Enterprise", price: "Custom / Invoiced", alias: "enterprise" },
  ];

  return (
    <div className="space-y-8">
      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-white">Plans & Subscriptions</h1>
          <p className="text-sm text-slate-400">
            Monitor tier distributions, grant promotional access, or manually provision enterprise agreements.
          </p>
        </div>
        <Link
          href="/admin/plans/cms"
          className="inline-flex items-center justify-center gap-2 rounded-xl bg-indigo-600 px-4 py-2.5 text-sm font-semibold text-white shadow-lg shadow-indigo-500/20 transition-all hover:bg-indigo-500 active:scale-95"
        >
          <Settings className="h-4 w-4" />
          Manage Plans CMS
        </Link>
      </div>

      {/* Plan Cards */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {planTiers.map((tier) => {
          const subscriberCount =
            stats?.users_by_plan?.[tier.alias] ||
            stats?.users_by_plan?.[tier.name.toLowerCase()] ||
            0;
          return (
            <div
              key={tier.name}
              className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5 backdrop-blur-sm"
            >
              <div className="flex items-center justify-between">
                <span className="text-xs font-semibold uppercase tracking-wider text-indigo-400">
                  {tier.name}
                </span>
                <span className="rounded-full bg-slate-800 px-2 py-0.5 text-[10px] text-slate-400">
                  {tier.price}
                </span>
              </div>
              <div className="mt-3">
                <div className="text-3xl font-bold text-white tracking-tight">{subscriberCount}</div>
                <p className="mt-1 text-xs text-slate-400">Active subscribers</p>
              </div>
            </div>
          );
        })}
      </div>

      {/* Quick Grant Subscription Tool */}
      <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-6 backdrop-blur-sm">
        <div className="flex items-center gap-2 mb-4">
          <UserPlus className="h-5 w-5 text-indigo-400" />
          <h2 className="text-base font-semibold text-white">Manual Subscription Provisioning</h2>
        </div>
        <p className="text-xs text-slate-400 mb-6 max-w-2xl">
          Instantly grant, extend, or override a plan for any user by email. This bypasses the payment gateway
          and logs an immutable audit trail entry.
        </p>

        {feedback && (
          <div
            className={`mb-6 flex items-center gap-2 rounded-xl p-3 text-xs border ${
              feedback.type === "success"
                ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-300"
                : "border-red-500/30 bg-red-500/10 text-red-300"
            }`}
          >
            {feedback.type === "success" ? (
              <CheckCircle2 className="h-4 w-4 text-emerald-400 shrink-0" />
            ) : (
              <AlertCircle className="h-4 w-4 text-red-400 shrink-0" />
            )}
            {feedback.message}
          </div>
        )}

        <form onSubmit={handleGrantPlan} className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-4">
          <div>
            <label className="text-xs text-slate-400">Target User Email</label>
            <input
              type="email"
              required
              placeholder="user@example.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="mt-1 w-full rounded-xl border border-slate-800 bg-slate-950 p-2.5 text-xs text-white placeholder-slate-500 focus:border-indigo-500 focus:outline-none"
            />
          </div>

          <div>
            <label className="text-xs text-slate-400">Plan Tier</label>
            <select
              value={plan}
              onChange={(e) => setPlan(e.target.value)}
              className="mt-1 w-full rounded-xl border border-slate-800 bg-slate-950 p-2.5 text-xs text-white focus:border-indigo-500 focus:outline-none"
            >
              <option value="Lite Plan">Lite Plan</option>
              <option value="Growth Plan">Growth Plan</option>
              <option value="Pro Plan">Pro Plan</option>
              <option value="Enterprise">Enterprise</option>
              <option value="free">Free (Revoke access)</option>
            </select>
          </div>

          <div>
            <label className="text-xs text-slate-400">Billing Cycle</label>
            <select
              value={cycle}
              onChange={(e) => setCycle(e.target.value)}
              className="mt-1 w-full rounded-xl border border-slate-800 bg-slate-950 p-2.5 text-xs text-white focus:border-indigo-500 focus:outline-none"
            >
              <option value="monthly">Monthly (+30 days)</option>
              <option value="yearly">Yearly (+365 days)</option>
            </select>
          </div>

          <div>
            <label className="text-xs text-slate-400">Reason / Reference</label>
            <input
              type="text"
              placeholder="e.g. Sales pilot, annual PO #1029"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              className="mt-1 w-full rounded-xl border border-slate-800 bg-slate-950 p-2.5 text-xs text-white placeholder-slate-500 focus:border-indigo-500 focus:outline-none"
            />
          </div>

          <div className="md:col-span-2 lg:col-span-4 flex justify-end">
            <button
              type="submit"
              disabled={granting}
              className="rounded-xl bg-indigo-600 px-5 py-2.5 text-xs font-semibold text-white hover:bg-indigo-500 disabled:opacity-50 transition"
            >
              {granting ? "Applying Plan..." : "Grant / Update Subscription"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
