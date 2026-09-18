"use client";

import React, { useEffect, useState } from "react";
import { adminApi } from "@/lib/admin-api";
import { FileText, Shield, Activity, RefreshCw, ChevronLeft, ChevronRight, DollarSign } from "lucide-react";

export default function AdminLogsPage() {
  const [activeTab, setActiveTab] = useState<"audit" | "usage">("audit");

  // Audit Logs State
  const [auditLogs, setAuditLogs] = useState<any[]>([]);
  const [auditTotal, setAuditTotal] = useState(0);
  const [auditPage, setAuditPage] = useState(1);
  const [auditActionFilter, setAuditActionFilter] = useState("");

  // Usage Logs State
  const [usageLogs, setUsageLogs] = useState<any[]>([]);
  const [usageTotal, setUsageTotal] = useState(0);
  const [usagePage, setUsagePage] = useState(1);
  const [usageTypeFilter, setUsageTypeFilter] = useState("");

  const [loading, setLoading] = useState(true);

  const fetchAuditLogs = async () => {
    try {
      setLoading(true);
      const params = new URLSearchParams();
      params.set("page", auditPage.toString());
      params.set("limit", "20");
      if (auditActionFilter) params.set("action", auditActionFilter);

      const data = await adminApi.get(`/api/admin/audit-logs?${params.toString()}`);
      setAuditLogs(data.logs || []);
      setAuditTotal(data.total || 0);
    } catch (err) {
      console.error("Failed to load audit logs:", err);
    } finally {
      setLoading(false);
    }
  };

  const fetchUsageLogs = async () => {
    try {
      setLoading(true);
      const params = new URLSearchParams();
      params.set("page", usagePage.toString());
      params.set("limit", "20");
      if (usageTypeFilter) params.set("activity_type", usageTypeFilter);

      const data = await adminApi.get(`/api/admin/usage-logs?${params.toString()}`);
      setUsageLogs(data.logs || []);
      setUsageTotal(data.total || 0);
    } catch (err) {
      console.error("Failed to load usage logs:", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (activeTab === "audit") {
      fetchAuditLogs();
    } else {
      fetchUsageLogs();
    }
  }, [activeTab, auditPage, auditActionFilter, usagePage, usageTypeFilter]);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-white">System Audits & Usage</h1>
          <p className="text-sm text-slate-400">
            Comprehensive audit logs for security compliance and live provider compute telemetry.
          </p>
        </div>
        <button
          onClick={activeTab === "audit" ? fetchAuditLogs : fetchUsageLogs}
          disabled={loading}
          className="inline-flex items-center gap-2 rounded-xl border border-slate-800 bg-slate-900 px-3 py-2 text-xs font-semibold text-slate-300 transition hover:bg-slate-800"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
          Refresh
        </button>
      </div>

      {/* Tabs */}
      <div className="flex items-center gap-2 border-b border-slate-800 pb-2">
        <button
          onClick={() => setActiveTab("audit")}
          className={`flex items-center gap-2 rounded-xl px-4 py-2 text-xs font-semibold transition ${
            activeTab === "audit"
              ? "bg-indigo-600/20 text-indigo-400 border border-indigo-500/30"
              : "text-slate-400 hover:text-white"
          }`}
        >
          <Shield className="h-4 w-4" />
          Admin Audit Logs ({auditTotal})
        </button>
        <button
          onClick={() => setActiveTab("usage")}
          className={`flex items-center gap-2 rounded-xl px-4 py-2 text-xs font-semibold transition ${
            activeTab === "usage"
              ? "bg-indigo-600/20 text-indigo-400 border border-indigo-500/30"
              : "text-slate-400 hover:text-white"
          }`}
        >
          <Activity className="h-4 w-4" />
          Platform Usage & Costs ({usageTotal})
        </button>
      </div>

      {/* ── TAB 1: AUDIT LOGS ────────────────────────────────────────────────── */}
      {activeTab === "audit" && (
        <div className="space-y-4">
          <div className="flex justify-end">
            <select
              value={auditActionFilter}
              onChange={(e) => {
                setAuditActionFilter(e.target.value);
                setAuditPage(1);
              }}
              className="rounded-xl border border-slate-800 bg-slate-950 px-3 py-2 text-xs text-slate-300 focus:outline-none"
            >
              <option value="">All Actions</option>
              <option value="grant_plan">Grant Plan</option>
              <option value="grant_credits">Grant Credits</option>
              <option value="suspend_user">Suspend User</option>
              <option value="unsuspend_user">Unsuspend User</option>
              <option value="change_role">Change Role</option>
              <option value="refund_payment">Refund Payment</option>
            </select>
          </div>

          <div className="overflow-hidden rounded-2xl border border-slate-800 bg-slate-900/60 backdrop-blur-sm">
            <table className="w-full text-left text-xs">
              <thead className="border-b border-slate-800 bg-slate-950/60 text-slate-400">
                <tr>
                  <th className="px-4 py-3.5 font-medium">Timestamp</th>
                  <th className="px-4 py-3.5 font-medium">Action</th>
                  <th className="px-4 py-3.5 font-medium">Admin ID</th>
                  <th className="px-4 py-3.5 font-medium">Target</th>
                  <th className="px-4 py-3.5 font-medium">Details</th>
                  <th className="px-4 py-3.5 font-medium">IP Address</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/80">
                {loading ? (
                  <tr>
                    <td colSpan={6} className="py-12 text-center text-slate-500">
                      Loading audit records...
                    </td>
                  </tr>
                ) : auditLogs.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="py-12 text-center text-slate-500">
                      No audit events recorded yet.
                    </td>
                  </tr>
                ) : (
                  auditLogs.map((log) => (
                    <tr key={log.id} className="hover:bg-slate-800/30 transition">
                      <td className="px-4 py-3 text-slate-400">{new Date(log.created_at).toLocaleString()}</td>
                      <td className="px-4 py-3">
                        <span className="rounded bg-indigo-500/10 px-2 py-0.5 text-[10px] font-semibold text-indigo-300 border border-indigo-500/20 uppercase">
                          {log.action?.replace("_", " ")}
                        </span>
                      </td>
                      <td className="px-4 py-3 font-mono text-[11px] text-slate-400">
                        {log.admin_user_id?.slice(0, 8)}...
                      </td>
                      <td className="px-4 py-3 text-slate-300">
                        <span className="font-semibold text-slate-400">{log.target_type}:</span>{" "}
                        <span className="font-mono text-[11px]">{log.target_id?.slice(0, 8)}...</span>
                      </td>
                      <td className="px-4 py-3 font-mono text-[11px] text-slate-300 max-w-xs truncate">
                        {JSON.stringify(log.details)}
                      </td>
                      <td className="px-4 py-3 font-mono text-[11px] text-slate-400">{log.ip_address || "N/A"}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ── TAB 2: USAGE LOGS ────────────────────────────────────────────────── */}
      {activeTab === "usage" && (
        <div className="space-y-4">
          <div className="flex justify-end">
            <select
              value={usageTypeFilter}
              onChange={(e) => {
                setUsageTypeFilter(e.target.value);
                setUsagePage(1);
              }}
              className="rounded-xl border border-slate-800 bg-slate-950 px-3 py-2 text-xs text-slate-300 focus:outline-none"
            >
              <option value="">All Activity Types</option>
              <option value="analysis">Analysis Run</option>
              <option value="llm_call">LLM Call</option>
              <option value="deep_research">Deep Research</option>
              <option value="llms_txt">LLMS.txt Generator</option>
              <option value="seo_analyzer">SEO Audit</option>
            </select>
          </div>

          <div className="overflow-hidden rounded-2xl border border-slate-800 bg-slate-900/60 backdrop-blur-sm">
            <table className="w-full text-left text-xs">
              <thead className="border-b border-slate-800 bg-slate-950/60 text-slate-400">
                <tr>
                  <th className="px-4 py-3.5 font-medium">Timestamp</th>
                  <th className="px-4 py-3.5 font-medium">Activity</th>
                  <th className="px-4 py-3.5 font-medium">User ID</th>
                  <th className="px-4 py-3.5 font-medium">Provider / Model</th>
                  <th className="px-4 py-3.5 font-medium">Input/Output</th>
                  <th className="px-4 py-3.5 font-medium">Est. Cost</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/80">
                {loading ? (
                  <tr>
                    <td colSpan={6} className="py-12 text-center text-slate-500">
                      Loading usage records...
                    </td>
                  </tr>
                ) : usageLogs.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="py-12 text-center text-slate-500">
                      No usage records found.
                    </td>
                  </tr>
                ) : (
                  usageLogs.map((log) => (
                    <tr key={log.id} className="hover:bg-slate-800/30 transition">
                      <td className="px-4 py-3 text-slate-400">{new Date(log.created_at).toLocaleString()}</td>
                      <td className="px-4 py-3 capitalize font-medium text-slate-300">
                        {log.activity_type}
                      </td>
                      <td className="px-4 py-3 font-mono text-[11px] text-slate-400">
                        {log.user_id ? `${log.user_id.slice(0, 8)}...` : "N/A"}
                      </td>
                      <td className="px-4 py-3 font-medium text-indigo-400 capitalize">
                        {log.llm_name || "N/A"}
                      </td>
                      <td className="px-4 py-3 text-slate-300 font-mono text-[11px]">
                        {log.prompt_chars} in / {log.response_chars} out
                      </td>
                      <td className="px-4 py-3 font-mono font-medium text-emerald-400">
                        ${Number(log.est_cost_usd || 0).toFixed(4)}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
