"use client";

import React, { ReactNode } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useAuth } from "@/contexts/AuthContext";
import {
  ShieldAlert,
  Users,
  CreditCard,
  Layers,
  FileText,
  Activity,
  ArrowLeft,
  LogOut,
  Sparkles,
  ShieldCheck,
} from "lucide-react";

interface AdminLayoutProps {
  children: ReactNode;
}

export default function AdminLayout({ children }: AdminLayoutProps) {
  const { isAuthenticated, isLoading, isAdmin, isSuperAdmin, email, logout } = useAuth();
  const pathname = usePathname();
  const router = useRouter();

  if (isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-950 text-white">
        <div className="flex flex-col items-center gap-3">
          <div className="h-8 w-8 animate-spin rounded-full border-4 border-indigo-500 border-t-transparent" />
          <p className="text-sm text-slate-400">Verifying administrative credentials...</p>
        </div>
      </div>
    );
  }

  if (!isAuthenticated) {
    router.push("/login");
    return null;
  }

  if (!isAdmin) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-950 p-6 text-white">
        <div className="max-w-md rounded-2xl border border-red-500/20 bg-slate-900/90 p-8 text-center shadow-2xl backdrop-blur-xl">
          <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-full bg-red-500/10 text-red-400">
            <ShieldAlert className="h-8 w-8" />
          </div>
          <h1 className="mt-4 text-2xl font-bold tracking-tight text-white">Access Denied</h1>
          <p className="mt-2 text-sm text-slate-400">
            Your account ({email}) does not have administrative permissions.
          </p>
          <div className="mt-6 flex flex-col gap-2">
            <Link
              href="/dashboard"
              className="inline-flex items-center justify-center gap-2 rounded-xl bg-indigo-600 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-indigo-500"
            >
              <ArrowLeft className="h-4 w-4" />
              Return to User Dashboard
            </Link>
            <button
              onClick={logout}
              className="inline-flex items-center justify-center gap-2 rounded-xl border border-slate-700 bg-slate-800 px-4 py-2.5 text-sm font-semibold text-slate-300 transition hover:bg-slate-700"
            >
              <LogOut className="h-4 w-4" />
              Sign Out
            </button>
          </div>
        </div>
      </div>
    );
  }

  const navItems = [
    { href: "/admin", label: "Overview", icon: Activity, exact: true },
    { href: "/admin/users", label: "Users & Accounts", icon: Users },
    { href: "/admin/plans", label: "Plans & Subscriptions", icon: Layers },
    { href: "/admin/payments", label: "Payments & Refunds", icon: CreditCard },
    { href: "/admin/logs", label: "Audits & Usage", icon: FileText },
  ];

  return (
    <div className="flex min-h-screen bg-slate-950 text-slate-100">
      {/* ── Admin Sidebar ─────────────────────────────────────────────────── */}
      <aside className="sticky top-0 flex h-screen w-64 flex-col border-r border-slate-800 bg-slate-900/60 p-4 backdrop-blur-md">
        {/* Brand */}
        <div className="mb-6 flex items-center gap-3 px-2">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-tr from-indigo-600 to-violet-500 shadow-md shadow-indigo-500/20">
            <ShieldCheck className="h-6 w-6 text-white" />
          </div>
          <div>
            <h2 className="text-base font-bold text-white">GEO Admin</h2>
            <div className="flex items-center gap-1.5">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
              <span className="text-xs text-slate-400">
                {isSuperAdmin ? "Super Admin" : "Staff Admin"}
              </span>
            </div>
          </div>
        </div>

        {/* Navigation */}
        <nav className="flex-1 space-y-1">
          {navItems.map((item) => {
            const isActive = item.exact
              ? pathname === item.href
              : pathname.startsWith(item.href);
            const Icon = item.icon;
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition ${
                  isActive
                    ? "bg-indigo-600/15 text-indigo-400 border border-indigo-500/20 shadow-sm"
                    : "text-slate-400 hover:bg-slate-800/60 hover:text-slate-200"
                }`}
              >
                <Icon className={`h-4 w-4 ${isActive ? "text-indigo-400" : "text-slate-400"}`} />
                {item.label}
              </Link>
            );
          })}
        </nav>

        {/* Footer Actions */}
        <div className="space-y-2 border-t border-slate-800 pt-4">
          <Link
            href="/dashboard"
            className="flex items-center gap-2 rounded-xl px-3 py-2 text-xs font-medium text-slate-400 transition hover:bg-slate-800 hover:text-slate-200"
          >
            <ArrowLeft className="h-4 w-4" />
            Back to User Portal
          </Link>
          <div className="flex items-center justify-between rounded-xl bg-slate-900/80 p-2.5 border border-slate-800/80">
            <div className="overflow-hidden">
              <p className="truncate text-xs font-medium text-slate-200">{email}</p>
              <p className="text-[10px] text-indigo-400 capitalize">{isSuperAdmin ? "Super Admin" : "Admin"}</p>
            </div>
            <button
              onClick={logout}
              title="Sign Out"
              className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-800 hover:text-red-400 transition"
            >
              <LogOut className="h-4 w-4" />
            </button>
          </div>
        </div>
      </aside>

      {/* ── Main Content Area ────────────────────────────────────────────── */}
      <main className="flex-1 overflow-y-auto p-8">
        <div className="mx-auto max-w-7xl">{children}</div>
      </main>
    </div>
  );
}
