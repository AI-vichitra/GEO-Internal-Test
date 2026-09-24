"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { plansApi, PlanItem } from "@/lib/admin-api";
import { useAuth } from "@/contexts/AuthContext";
import {
  ArrowLeft,
  RefreshCw,
  Plus,
  Edit2,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Clock,
  Layers,
  Sparkles,
  ShieldAlert,
  Save,
  Trash2,
  Info
} from "lucide-react";

export default function PlansCmsPage() {
  const { isSuperAdmin, refreshUser } = useAuth();
  const [plans, setPlans] = useState<PlanItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  // Edit Drawer / Modal state
  const [editingPlan, setEditingPlan] = useState<PlanItem | null>(null);
  const [isCreating, setIsCreating] = useState(false);
  const [formState, setFormState] = useState<{
    display_name: string;
    description: string;
    badge_text: string;
    monthly_price_inr: number;
    yearly_price_inr: number;
    features: string[];
    limits: {
      max_projects: number;
      max_prompts_per_project: number;
      max_competitors: number;
    };
    is_active: boolean;
    is_popular: boolean;
    cta_text: string;
    sort_order: number;
    grandfather_existing_subscribers: boolean;
    change_reason: string;
    name?: string;
  }>({
    display_name: "",
    description: "",
    badge_text: "",
    monthly_price_inr: 0,
    yearly_price_inr: 0,
    features: [],
    limits: { max_projects: 1, max_prompts_per_project: 5, max_competitors: 10 },
    is_active: true,
    is_popular: false,
    cta_text: "Get Started",
    sort_order: 0,
    grandfather_existing_subscribers: false,
    change_reason: "",
  });
  const [newFeatureText, setNewFeatureText] = useState("");
  const [saving, setSaving] = useState(false);

  const fetchPlans = async () => {
    try {
      setLoading(true);
      setError(null);
      const res = await plansApi.list();
      setPlans(res.plans || []);
    } catch (err: any) {
      setError(err.message || "Failed to load plans");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchPlans();
  }, []);

  const openEdit = (plan: PlanItem) => {
    setIsCreating(false);
    setEditingPlan(plan);
    setFormState({
      display_name: plan.display_name,
      description: plan.description || "",
      badge_text: plan.badge_text || "",
      monthly_price_inr: Math.round(plan.monthly_price_paise / 100),
      yearly_price_inr: Math.round(plan.yearly_price_paise / 100),
      features: [...(plan.features || [])],
      limits: {
        max_projects: plan.limits?.max_projects || 1,
        max_prompts_per_project: plan.limits?.max_prompts_per_project || 5,
        max_competitors: plan.limits?.max_competitors || 10,
      },
      is_active: plan.is_active,
      is_popular: plan.is_popular,
      cta_text: plan.cta_text || "Get Started",
      sort_order: plan.sort_order || 0,
      grandfather_existing_subscribers: plan.grandfather_existing_subscribers || false,
      change_reason: "",
    });
    setNewFeatureText("");
  };

  const openCreate = () => {
    setIsCreating(true);
    setEditingPlan(null);
    setFormState({
      name: "",
      display_name: "",
      description: "",
      badge_text: "",
      monthly_price_inr: 0,
      yearly_price_inr: 0,
      features: ["1 Brand Project", "AI Visibility tracking"],
      limits: { max_projects: 5, max_prompts_per_project: 15, max_competitors: 10 },
      is_active: true,
      is_popular: false,
      cta_text: "Get Started",
      sort_order: (plans.length || 0) + 1,
      grandfather_existing_subscribers: false,
      change_reason: "Initial plan creation",
    });
    setNewFeatureText("");
  };

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!isSuperAdmin) {
      setError("Super Admin permissions required to modify plans.");
      return;
    }

    try {
      setSaving(true);
      setError(null);
      setSuccessMsg(null);

      const payload: any = {
        display_name: formState.display_name,
        description: formState.description || null,
        badge_text: formState.badge_text || null,
        monthly_price_paise: Math.round(Number(formState.monthly_price_inr) * 100),
        yearly_price_paise: Math.round(Number(formState.yearly_price_inr) * 100),
        currency: "INR",
        features: formState.features,
        limits: formState.limits,
        is_active: formState.is_active,
        is_popular: formState.is_popular,
        cta_text: formState.cta_text,
        sort_order: Number(formState.sort_order),
        grandfather_existing_subscribers: formState.grandfather_existing_subscribers,
        change_reason: formState.change_reason || "CMS Update",
      };

      if (isCreating) {
        payload.name = (formState.name || "").toLowerCase().trim();
        await plansApi.create(payload);
        setSuccessMsg(`Plan "${payload.display_name}" created successfully.`);
      } else if (editingPlan) {
        // Optimistic locking: pass expected_version
        payload.expected_version = editingPlan.version;
        await plansApi.update(editingPlan.id, payload);
        setSuccessMsg(`Plan "${formState.display_name}" updated successfully (v${editingPlan.version + 1}).`);
      }

      setEditingPlan(null);
      setIsCreating(false);
      await fetchPlans();
      // Immediately re-sync the current user's plan limits so the admin
      // sees the updated limits reflected in the same session.
      refreshUser().catch(() => {/* silent */});
    } catch (err: any) {
      if (err.message && err.message.includes("409")) {
        setError("Conflict detected: This plan was modified by another administrator. Please refresh and review latest changes.");
      } else {
        setError(err.message || "Failed to save plan changes.");
      }
    } finally {
      setSaving(false);
    }
  };

  const addFeature = () => {
    if (newFeatureText.trim()) {
      setFormState({
        ...formState,
        features: [...formState.features, newFeatureText.trim()],
      });
      setNewFeatureText("");
    }
  };

  const removeFeature = (index: number) => {
    setFormState({
      ...formState,
      features: formState.features.filter((_, i) => i !== index),
    });
  };

  return (
    <div className="space-y-6">
      {/* Top Navigation & Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <Link
              href="/admin/plans"
              className="inline-flex items-center gap-1 text-xs text-indigo-400 hover:text-indigo-300 transition-colors"
            >
              <ArrowLeft className="h-3 w-3" />
              Back to Subscriptions
            </Link>
          </div>
          <h1 className="text-2xl font-bold tracking-tight text-white flex items-center gap-2">
            <Layers className="h-6 w-6 text-indigo-400" />
            Plans CMS (Content Management System)
          </h1>
          <p className="text-sm text-slate-400">
            Control live pricing, feature bullets, project limits, and tier visibility without redeploying code.
          </p>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={fetchPlans}
            disabled={loading}
            className="inline-flex items-center gap-1.5 rounded-xl border border-slate-700 bg-slate-800/80 px-3 py-2 text-xs font-semibold text-slate-300 transition-all hover:bg-slate-700 hover:text-white"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
            Refresh
          </button>
          {isSuperAdmin && (
            <button
              onClick={openCreate}
              className="inline-flex items-center gap-1.5 rounded-xl bg-indigo-600 px-3.5 py-2 text-xs font-semibold text-white shadow-lg shadow-indigo-500/20 transition-all hover:bg-indigo-500 active:scale-95"
            >
              <Plus className="h-3.5 w-3.5" />
              New Plan
            </button>
          )}
        </div>
      </div>

      {/* Info Notice on Cache Propagation */}
      <div className="rounded-xl border border-indigo-900/50 bg-indigo-950/20 p-4 text-xs text-indigo-300 flex items-start gap-3">
        <Info className="h-5 w-5 text-indigo-400 shrink-0 mt-0.5" />
        <div>
          <span className="font-semibold text-white">Live Propagation Policy:</span> Plan edits invalidate backend memory cache immediately. Browser and public CDN caches accept a 60-second propagation window. Razorpay payments and API limit checks always evaluate against authoritative server records.
        </div>
      </div>

      {/* Alerts */}
      {error && (
        <div className="rounded-xl border border-rose-500/40 bg-rose-500/10 p-4 text-sm text-rose-300 flex items-center gap-3">
          <AlertTriangle className="h-5 w-5 text-rose-400 shrink-0" />
          <span>{error}</span>
        </div>
      )}
      {successMsg && (
        <div className="rounded-xl border border-emerald-500/40 bg-emerald-500/10 p-4 text-sm text-emerald-300 flex items-center gap-3">
          <CheckCircle2 className="h-5 w-5 text-emerald-400 shrink-0" />
          <span>{successMsg}</span>
        </div>
      )}

      {/* Plans List Table */}
      <div className="overflow-hidden rounded-2xl border border-slate-800 bg-slate-900/60 shadow-xl backdrop-blur-sm">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs text-slate-300">
            <thead className="border-b border-slate-800 bg-slate-900/90 text-[11px] font-semibold uppercase tracking-wider text-slate-400">
              <tr>
                <th className="px-4 py-3.5">Order</th>
                <th className="px-4 py-3.5">Plan Name</th>
                <th className="px-4 py-3.5">Price (Monthly / Yearly)</th>
                <th className="px-4 py-3.5">Limits</th>
                <th className="px-4 py-3.5">Status</th>
                <th className="px-4 py-3.5">Subscribers</th>
                <th className="px-4 py-3.5">Version</th>
                <th className="px-4 py-3.5 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60">
              {loading && plans.length === 0 ? (
                <tr>
                  <td colSpan={8} className="py-12 text-center text-slate-500">
                    <RefreshCw className="mx-auto h-6 w-6 animate-spin mb-2" />
                    Loading pricing plans...
                  </td>
                </tr>
              ) : plans.length === 0 ? (
                <tr>
                  <td colSpan={8} className="py-12 text-center text-slate-500">
                    No plans found in database. Run the migration to seed canonical plans.
                  </td>
                </tr>
              ) : (
                plans.map((p) => {
                  const monthlyInr = Math.round(p.monthly_price_paise / 100);
                  const yearlyInr = Math.round(p.yearly_price_paise / 100);

                  return (
                    <tr key={p.id} className="transition-colors hover:bg-slate-800/30">
                      <td className="px-4 py-3 text-slate-500 font-mono">#{p.sort_order}</td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2">
                          <span className="font-semibold text-white">{p.display_name}</span>
                          <span className="font-mono text-[10px] text-slate-400 bg-slate-800 px-1.5 py-0.5 rounded">
                            {p.name}
                          </span>
                          {p.is_popular && (
                            <span className="rounded bg-indigo-500/20 px-1.5 py-0.5 text-[9px] font-semibold text-indigo-400">
                              POPULAR
                            </span>
                          )}
                        </div>
                        {p.description && (
                          <div className="text-[11px] text-slate-400 truncate max-w-xs">{p.description}</div>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <div className="font-medium text-white">
                          ₹{monthlyInr.toLocaleString("en-IN")}{" "}
                          <span className="text-[10px] text-slate-400">/ mo</span>
                        </div>
                        <div className="text-[10px] text-slate-400">
                          ₹{yearlyInr.toLocaleString("en-IN")} / yr
                        </div>
                      </td>
                      <td className="px-4 py-3 text-[11px]">
                        <div>Projects: <span className="font-semibold text-slate-200">{p.limits?.max_projects ?? "—"}</span></div>
                        <div>Prompts: <span className="font-semibold text-slate-200">{p.limits?.max_prompts_per_project ?? "—"}</span></div>
                        <div>Competitors: <span className="font-semibold text-slate-200">{p.limits?.max_competitors ?? "—"}</span></div>
                      </td>
                      <td className="px-4 py-3">
                        {p.is_active ? (
                          <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500/10 px-2 py-0.5 text-[10px] font-medium text-emerald-400">
                            <CheckCircle2 className="h-3 w-3" /> Active
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1 rounded-full bg-slate-700/50 px-2 py-0.5 text-[10px] font-medium text-slate-400">
                            <XCircle className="h-3 w-3" /> Hidden
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-3 font-mono font-semibold text-slate-200">
                        {p.subscriber_count ?? 0}
                      </td>
                      <td className="px-4 py-3">
                        <span className="font-mono text-[10px] rounded bg-slate-800 px-2 py-0.5 text-slate-300">
                          v{p.version ?? 1}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-right">
                        <button
                          onClick={() => openEdit(p)}
                          className="inline-flex items-center gap-1 rounded-lg border border-slate-700 bg-slate-800/80 px-2.5 py-1.5 text-[11px] font-medium text-slate-200 transition-colors hover:bg-slate-700 hover:text-white"
                        >
                          <Edit2 className="h-3 w-3 text-indigo-400" />
                          Edit
                        </button>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Slide-over / Edit Modal */}
      {(editingPlan || isCreating) && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-4 backdrop-blur-sm">
          <div className="relative max-h-[92vh] w-full max-w-2xl overflow-y-auto rounded-2xl border border-slate-700 bg-slate-900 p-6 shadow-2xl">
            <div className="flex items-center justify-between border-b border-slate-800 pb-4 mb-4">
              <div>
                <h2 className="text-lg font-bold text-white flex items-center gap-2">
                  <Edit2 className="h-4 w-4 text-indigo-400" />
                  {isCreating ? "Create New Plan" : `Edit Plan: ${editingPlan?.display_name}`}
                </h2>
                {!isCreating && editingPlan && (
                  <p className="text-xs text-slate-400">
                    Canonical Key: <span className="font-mono text-indigo-300">{editingPlan.name}</span> | Current Version: <span className="font-mono text-indigo-300">v{editingPlan.version}</span>
                  </p>
                )}
              </div>
              <button
                onClick={() => {
                  setEditingPlan(null);
                  setIsCreating(false);
                }}
                className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-800 hover:text-white"
              >
                ✕
              </button>
            </div>

            <form onSubmit={handleSave} className="space-y-4">
              {isCreating && (
                <div>
                  <label className="block text-xs font-semibold text-slate-300 mb-1">
                    Canonical Key (Unique Slug) *
                  </label>
                  <input
                    type="text"
                    required
                    placeholder="e.g. starter"
                    value={formState.name}
                    onChange={(e) => setFormState({ ...formState, name: e.target.value })}
                    className="w-full rounded-xl border border-slate-700 bg-slate-800 px-3 py-2 text-xs text-white focus:border-indigo-500 focus:outline-none"
                  />
                  <p className="text-[10px] text-slate-500 mt-1">Lowercase letters, numbers, hyphens only.</p>
                </div>
              )}

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-semibold text-slate-300 mb-1">Display Name *</label>
                  <input
                    type="text"
                    required
                    value={formState.display_name}
                    onChange={(e) => setFormState({ ...formState, display_name: e.target.value })}
                    className="w-full rounded-xl border border-slate-700 bg-slate-800 px-3 py-2 text-xs text-white focus:border-indigo-500 focus:outline-none"
                  />
                </div>
                <div>
                  <label className="block text-xs font-semibold text-slate-300 mb-1">Badge Text (Optional)</label>
                  <input
                    type="text"
                    placeholder="e.g. MOST POPULAR"
                    value={formState.badge_text}
                    onChange={(e) => setFormState({ ...formState, badge_text: e.target.value })}
                    className="w-full rounded-xl border border-slate-700 bg-slate-800 px-3 py-2 text-xs text-white focus:border-indigo-500 focus:outline-none"
                  />
                </div>
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-300 mb-1">Description</label>
                <textarea
                  rows={2}
                  value={formState.description}
                  onChange={(e) => setFormState({ ...formState, description: e.target.value })}
                  className="w-full rounded-xl border border-slate-700 bg-slate-800 px-3 py-2 text-xs text-white focus:border-indigo-500 focus:outline-none"
                />
              </div>

              {/* Pricing in INR */}
              <div className="rounded-xl border border-slate-800 bg-slate-950/40 p-3.5 space-y-3">
                <div className="text-xs font-semibold text-indigo-400 flex items-center justify-between">
                  <span>Pricing Configuration (₹ INR)</span>
                  <span className="text-[10px] text-slate-500">Stored automatically in paise</span>
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <div>
                    <label className="block text-[11px] text-slate-300 mb-1">Monthly Price (₹) *</label>
                    <input
                      type="number"
                      min="0"
                      required
                      value={formState.monthly_price_inr}
                      onChange={(e) => setFormState({ ...formState, monthly_price_inr: Number(e.target.value) })}
                      className="w-full rounded-xl border border-slate-700 bg-slate-800 px-3 py-2 text-xs text-white font-mono"
                    />
                  </div>
                  <div>
                    <label className="block text-[11px] text-slate-300 mb-1">Yearly Price (₹) *</label>
                    <input
                      type="number"
                      min="0"
                      required
                      value={formState.yearly_price_inr}
                      onChange={(e) => setFormState({ ...formState, yearly_price_inr: Number(e.target.value) })}
                      className="w-full rounded-xl border border-slate-700 bg-slate-800 px-3 py-2 text-xs text-white font-mono"
                    />
                  </div>
                </div>
              </div>

              {/* Limits Configuration */}
              <div className="rounded-xl border border-slate-800 bg-slate-950/40 p-3.5 space-y-3">
                <div className="text-xs font-semibold text-indigo-400">Account Limits Enforcement</div>
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                  <div>
                    <label className="block text-[10px] text-slate-400 mb-1">Max Projects</label>
                    <input
                      type="number"
                      min="1"
                      required
                      value={formState.limits.max_projects}
                      onChange={(e) =>
                        setFormState({
                          ...formState,
                          limits: { ...formState.limits, max_projects: Number(e.target.value) },
                        })
                      }
                      className="w-full rounded-xl border border-slate-700 bg-slate-800 px-3 py-2 text-xs text-white font-mono"
                    />
                  </div>
                  <div>
                    <label className="block text-[10px] text-slate-400 mb-1">Max Prompts / Project</label>
                    <input
                      type="number"
                      min="1"
                      required
                      value={formState.limits.max_prompts_per_project}
                      onChange={(e) =>
                        setFormState({
                          ...formState,
                          limits: { ...formState.limits, max_prompts_per_project: Number(e.target.value) },
                        })
                      }
                      className="w-full rounded-xl border border-slate-700 bg-slate-800 px-3 py-2 text-xs text-white font-mono"
                    />
                  </div>
                  <div>
                    <label className="block text-[10px] text-slate-400 mb-1">Max Competitors</label>
                    <input
                      type="number"
                      min="1"
                      required
                      value={formState.limits.max_competitors}
                      onChange={(e) =>
                        setFormState({
                          ...formState,
                          limits: { ...formState.limits, max_competitors: Number(e.target.value) },
                        })
                      }
                      className="w-full rounded-xl border border-slate-700 bg-slate-800 px-3 py-2 text-xs text-white font-mono"
                    />
                  </div>
                </div>
              </div>

              {/* Feature Bullets Editor */}
              <div>
                <label className="block text-xs font-semibold text-slate-300 mb-1">
                  Feature Bullets ({formState.features.length})
                </label>
                <div className="space-y-1.5 mb-2 max-h-40 overflow-y-auto">
                  {formState.features.map((feat, i) => (
                    <div key={i} className="flex items-center gap-2 rounded-lg bg-slate-800/80 px-2.5 py-1.5 text-xs">
                      <span className="text-slate-200 flex-1">{feat}</span>
                      <button
                        type="button"
                        onClick={() => removeFeature(i)}
                        className="text-slate-400 hover:text-rose-400"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  ))}
                </div>
                <div className="flex gap-2">
                  <input
                    type="text"
                    placeholder="Add bullet point..."
                    value={newFeatureText}
                    onChange={(e) => setNewFeatureText(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") {
                        e.preventDefault();
                        addFeature();
                      }
                    }}
                    className="flex-1 rounded-xl border border-slate-700 bg-slate-800 px-3 py-1.5 text-xs text-white"
                  />
                  <button
                    type="button"
                    onClick={addFeature}
                    className="rounded-xl border border-slate-700 bg-slate-800 px-3 py-1.5 text-xs font-medium text-slate-200 hover:bg-slate-700"
                  >
                    Add
                  </button>
                </div>
              </div>

              {/* Toggles & Options */}
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 border-t border-slate-800 pt-3">
                <label className="flex items-center gap-2 text-xs text-slate-300 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={formState.is_active}
                    onChange={(e) => setFormState({ ...formState, is_active: e.target.checked })}
                    className="rounded border-slate-700 bg-slate-800 text-indigo-600 focus:ring-0"
                  />
                  <span>Active (Visible)</span>
                </label>

                <label className="flex items-center gap-2 text-xs text-slate-300 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={formState.is_popular}
                    onChange={(e) => setFormState({ ...formState, is_popular: e.target.checked })}
                    className="rounded border-slate-700 bg-slate-800 text-indigo-600 focus:ring-0"
                  />
                  <span>Most Popular Badge</span>
                </label>

                <label className="flex items-center gap-2 text-xs text-slate-300 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={formState.grandfather_existing_subscribers}
                    onChange={(e) =>
                      setFormState({ ...formState, grandfather_existing_subscribers: e.target.checked })
                    }
                    className="rounded border-slate-700 bg-slate-800 text-indigo-600 focus:ring-0"
                  />
                  <span>Grandfather Active Users</span>
                </label>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-semibold text-slate-300 mb-1">CTA Button Text</label>
                  <input
                    type="text"
                    value={formState.cta_text}
                    onChange={(e) => setFormState({ ...formState, cta_text: e.target.value })}
                    className="w-full rounded-xl border border-slate-700 bg-slate-800 px-3 py-2 text-xs text-white"
                  />
                </div>
                <div>
                  <label className="block text-xs font-semibold text-slate-300 mb-1">Sort Order</label>
                  <input
                    type="number"
                    value={formState.sort_order}
                    onChange={(e) => setFormState({ ...formState, sort_order: Number(e.target.value) })}
                    className="w-full rounded-xl border border-slate-700 bg-slate-800 px-3 py-2 text-xs text-white font-mono"
                  />
                </div>
              </div>

              {/* Audit Reason */}
              <div>
                <label className="block text-xs font-semibold text-slate-300 mb-1">
                  Change Reason (Logged in Audit Trail)
                </label>
                <input
                  type="text"
                  placeholder="e.g. Q4 promotional pricing adjustment"
                  value={formState.change_reason}
                  onChange={(e) => setFormState({ ...formState, change_reason: e.target.value })}
                  className="w-full rounded-xl border border-slate-700 bg-slate-800 px-3 py-2 text-xs text-white"
                />
              </div>

              {/* Submit Buttons */}
              <div className="flex items-center justify-end gap-3 pt-4 border-t border-slate-800">
                <button
                  type="button"
                  onClick={() => {
                    setEditingPlan(null);
                    setIsCreating(false);
                  }}
                  className="rounded-xl border border-slate-700 px-4 py-2 text-xs font-semibold text-slate-300 hover:bg-slate-800"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={saving}
                  className="inline-flex items-center gap-1.5 rounded-xl bg-indigo-600 px-4 py-2 text-xs font-semibold text-white shadow-lg shadow-indigo-500/20 hover:bg-indigo-500 disabled:opacity-50"
                >
                  <Save className="h-3.5 w-3.5" />
                  {saving ? "Saving..." : isCreating ? "Create Plan" : "Save Changes"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
