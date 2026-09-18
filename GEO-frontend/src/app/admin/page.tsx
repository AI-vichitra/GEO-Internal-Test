"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { adminApi } from "@/lib/admin-api";
import {
  Users,
  CreditCard,
  Layers,
  Activity,
  UserX,
  DollarSign,
  ArrowUpRight,
  ShieldCheck,
  RefreshCw,
  FolderGit2
} from "lucide-react";

interface AdminStats {
  total_users: number;
  active_paid_users: number;
  suspended_users: number;
  total_sessions: number;
  total_projects: number;
  users_by_plan: Record<string, number>;
  total_est_cost_usd: number;
  recent_audits: Array<{
    id: string;
    action: string;
    target_type: string;
    target_id: string;
    details: any;
    created_at: string;
  }>;
}

export default function AdminOverviewPage() {
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchStats = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await adminApi.get<AdminStats>("/api/admin/stats");
      setStats(data);
    } catch (err: any) {
      setError(err.message || "Failed to load admin stats");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchStats();
  }, []);

  if (loading && !stats) {
    return (
      <div className="flex h-96 items-center justify-center">
        <div className="flex flex-col items-center gap-2">
          <div className="h-8 w-8 animate-spin rounded-full border-4 border-indigo-500 border-t-transparent" />
          <p className="text-xs text-slate-400">Loading system metrics...</p>
        </div>
      </div>
    );
  }

  const statCards = [
    {
      title: "Total Registered Users",
      value: stats?.total_users ?? 0,
      icon: Users,
      desc: "All time signups",
      color: "from-blue-500/20 to-indigo-500/20 text-blue-400",
      link: "/admin/users"
    },
    {
      title: "Active Subscriptions",
      value: stats?.active_paid_users ?? 0,
      icon: Layers,
      desc: "Users on paid plans",
      color: "from-emerald-500/20 to-teal-500/20 text-emerald-400",
      link: "/admin/plans"
    },
    {
      title: "Analysis Sessions",
      value: stats?.total_sessions ?? 0,
      icon: Activity,
      desc: "Total brand visibility runs",
      color: "from-violet-500/20 to-purple-500/20 text-violet-400"
    },
    {
      title: "Monitored Projects",
      value: stats?.total_projects ?? 0,
      icon: FolderGit2,
      desc: "Scheduled tracking brands",
      color: "from-amber-500/20 to-orange-500/20 text-amber-400"
    },
    {
      title: "Suspended Accounts",
      value: stats?.suspended_users ?? 0,
      icon: UserX,
      desc: "Access currently blocked",
      color: "from-rose-500/20 to-red-500/20 text-rose-400",
      link: "/admin/users?suspended=true"
    },
    {
      title: "Est. LLM API Spend",
      value: `$${(stats?.total_est_cost_usd ?? 0).toFixed(2)}`,
      icon: DollarSign,
      desc: "Approx. provider compute",
      color: "from-cyan-500/20 to-sky-500/20 text-cyan-400",
      link: "/admin/logs"
    },
  ];

  return (
    <div className="space-y-8">
      {/* Page Header */}
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-white">System Administration</h1>
          <p className="text-sm text-slate-400">
            Real-time platform metrics, tenant controls, and audit trails.
          </p>
        </div>
        <button
          onClick={fetchStats}
          disabled={loading}
          className="inline-flex items-center gap-2 rounded-xl border border-slate-800 bg-slate-900 px-4 py-2 text-xs font-semibold text-slate-300 transition hover:bg-slate-800 hover:text-white"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
          Refresh Metrics
        </button>
      </div>

      {error && (
        <div className="rounded-xl border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-300">
          {error}
        </div>
      )}

      {/* KPI Grid */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {statCards.map((card, idx) => {
          const Icon = card.icon;
          const CardWrapper = card.link ? Link : "div";
          return (
            <CardWrapper
              key={idx}
              href={card.link || "#"}
              className={`group relative overflow-hidden rounded-2xl border border-slate-800/80 bg-slate-900/60 p-5 backdrop-blur-sm transition ${
                card.link ? "hover:border-slate-700 hover:bg-slate-900" : ""
              }`}
            >
              <div className="flex items-center justify-between">
                <span className="text-xs font-medium text-slate-400">{card.title}</span>
                <div className={`rounded-xl p-2.5 bg-gradient-to-br ${card.color}`}>
                  <Icon className="h-5 w-5" />
                </div>
              </div>
              <div className="mt-3">
                <div className="text-2xl font-bold text-white tracking-tight">{card.value}</div>
                <div className="mt-1 flex items-center justify-between text-xs text-slate-400">
                  <span>{card.desc}</span>
                  {card.link && (
                    <ArrowUpRight className="h-3.5 w-3.5 opacity-0 transition group-hover:opacity-100 group-hover:translate-x-0.5" />
                  )}
                </div>
              </div>
            </CardWrapper>
          );
        })}
      </div>

      {/* Two Column Section: Plan Distribution & Recent Audits */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* Plan Breakdown */}
        <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-6 backdrop-blur-sm">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-base font-semibold text-white">Users by Subscription Plan</h2>
            <Link href="/admin/plans" className="text-xs text-indigo-400 hover:underline">
              Manage plans &rarr;
            </Link>
          </div>
          <div className="space-y-3">
            {Object.entries(stats?.users_by_plan || {}).map(([plan, count]) => {
              const total = stats?.total_users || 1;
              const percent = Math.round((count / total) * 100);
              return (
                <div key={plan} className="space-y-1">
                  <div className="flex justify-between text-xs">
                    <span className="font-medium uppercase tracking-wider text-slate-300">{plan}</span>
                    <span className="text-slate-400">
                      {count} ({percent}%)
                    </span>
                  </div>
                  <div className="h-2 w-full overflow-hidden rounded-full bg-slate-800">
                    <div
                      className="h-full bg-gradient-to-r from-indigo-500 to-violet-500 rounded-full"
                      style={{ width: `${percent}%` }}
                    />
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Recent Admin Audit Activity */}
        <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-6 backdrop-blur-sm">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-base font-semibold text-white">Recent Admin Activity</h2>
            <Link href="/admin/logs" className="text-xs text-indigo-400 hover:underline">
              View all logs &rarr;
            </Link>
          </div>
          <div className="space-y-3">
            {(stats?.recent_audits || []).length === 0 ? (
              <p className="text-xs text-slate-500 py-6 text-center">No recent admin operations logged.</p>
            ) : (
              (stats?.recent_audits || []).map((audit) => (
                <div
                  key={audit.id}
                  className="flex items-center justify-between rounded-xl border border-slate-800/80 bg-slate-950/50 p-3 text-xs"
                >
                  <div className="space-y-0.5">
                    <div className="flex items-center gap-2">
                      <span className="font-semibold text-indigo-400 uppercase tracking-wider text-[10px] rounded bg-indigo-500/10 px-1.5 py-0.5 border border-indigo-500/20">
                        {audit.action.replace("_", " ")}
                      </span>
                      <span className="text-slate-300 font-mono text-[11px]">
                        {audit.target_type}: {audit.target_id?.slice(0, 8)}...
                      </span>
                    </div>
                    <p className="text-[11px] text-slate-400">
                      {new Date(audit.created_at).toLocaleString()}
                    </p>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
