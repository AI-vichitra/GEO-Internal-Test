"use client";

import { useState, useEffect } from "react";
import { Switch } from "@/components/ui/switch";
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { CalendarClock, Clock, RefreshCw, CheckCircle2 } from "lucide-react";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "https://api.optimiseurbrand.tech";

interface SchedulerCardProps {
    /** UUID of the project to manage scheduling for */
    projectId: string;
}

interface ProjectSchedulerState {
    is_active: boolean;
    update_frequency: string;
    sync_status?: string;   // 'idle' | 'running'
    last_sync_at?: string;
}

const FREQUENCY_OPTIONS = [
    { value: "1h",  label: "Every 1 Hour" },
    { value: "6h",  label: "Every 6 Hours" },
    { value: "12h", label: "Every 12 Hours" },
    { value: "24h", label: "Every 24 Hours (Daily)" },
    { value: "48h", label: "Every 48 Hours" },
    { value: "7d",  label: "Every 7 Days (Weekly)" },
    { value: "14d", label: "Every 14 Days" },
    { value: "30d", label: "Every 30 Days (Monthly)" },
];

function formatLastSync(ts?: string): string {
    if (!ts) return "Never";
    const d = new Date(ts);
    return d.toLocaleString(undefined, {
        dateStyle: "medium",
        timeStyle: "short",
    });
}

export function SchedulerCard({ projectId }: SchedulerCardProps) {
    const [state, setState] = useState<ProjectSchedulerState>({
        is_active: false,
        update_frequency: "24h",
        sync_status: "idle",
    });
    const [isSaving, setIsSaving] = useState(false);
    const [savedMsg, setSavedMsg] = useState<string | null>(null);
    const [isLoading, setIsLoading] = useState(true);

    // Load current project settings
    useEffect(() => {
        const load = async () => {
            setIsLoading(true);
            try {
                const token = localStorage.getItem("token");
                const res = await fetch(`${API_BASE_URL}/api/projects/${projectId}`, {
                    headers: { Authorization: `Bearer ${token}` },
                });
                if (!res.ok) return;
                const data = await res.json();
                const p = data.project;
                setState({
                    is_active: p.is_active ?? false,
                    update_frequency: p.update_frequency ?? "24h",
                    sync_status: p.sync_status ?? "idle",
                    last_sync_at: p.last_sync_at,
                });
            } catch (e) {
                console.error("SchedulerCard: failed to load project", e);
            } finally {
                setIsLoading(false);
            }
        };
        load();
    }, [projectId]);

    const handleSave = async () => {
        setIsSaving(true);
        setSavedMsg(null);
        try {
            const token = localStorage.getItem("token");
            const res = await fetch(`${API_BASE_URL}/api/projects/${projectId}`, {
                method: "PUT",
                headers: {
                    "Content-Type": "application/json",
                    Authorization: `Bearer ${token}`,
                },
                body: JSON.stringify({
                    is_active: state.is_active,
                    update_frequency: state.update_frequency,
                }),
            });
            if (res.ok) {
                setSavedMsg("Settings saved successfully!");
                setTimeout(() => setSavedMsg(null), 3000);
            } else {
                setSavedMsg("Failed to save. Please try again.");
            }
        } catch (e) {
            setSavedMsg("Network error. Please try again.");
        } finally {
            setIsSaving(false);
        }
    };

    const isRunning = state.sync_status === "running";

    if (isLoading) {
        return (
            <Card className="border-gray-100 bg-white shadow-sm animate-pulse">
                <CardContent className="p-6 h-32" />
            </Card>
        );
    }

    return (
        <Card className="border-gray-100 bg-white shadow-sm overflow-hidden">
            {/* Teal accent bar at top */}
            <div className={`h-1 w-full ${state.is_active ? "bg-gradient-to-r from-teal-400 to-emerald-400" : "bg-gray-200"}`} />

            <CardHeader className="pb-2 pt-5 px-6">
                <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                        <div className={`p-2 rounded-lg ${state.is_active ? "bg-teal-50 text-teal-600" : "bg-gray-100 text-gray-500"}`}>
                            <CalendarClock className="h-5 w-5" />
                        </div>
                        <div>
                            <CardTitle className="text-base font-semibold text-gray-900">
                                Automated Scheduled Runs
                            </CardTitle>
                            <CardDescription className="text-xs text-gray-500 mt-0.5">
                                Automatically re-run analysis on a recurring schedule to track trends
                            </CardDescription>
                        </div>
                    </div>

                    {/* ON/OFF toggle */}
                    <div className="flex items-center gap-2">
                        <span className={`text-sm font-medium ${state.is_active ? "text-teal-600" : "text-gray-400"}`}>
                            {state.is_active ? "ON" : "OFF"}
                        </span>
                        <Switch
                            checked={state.is_active}
                            onCheckedChange={(val) => setState(s => ({ ...s, is_active: val }))}
                            className="data-[state=checked]:bg-teal-500"
                        />
                    </div>
                </div>
            </CardHeader>

            <CardContent className="px-6 pb-5 space-y-4">
                {/* Frequency selector + Save */}
                <div className="flex items-center gap-3">
                    <div className="flex-1">
                        <label className="text-xs font-medium text-gray-500 mb-1 block">Sync Frequency</label>
                        <Select
                            value={state.update_frequency}
                            onValueChange={(val) => setState(s => ({ ...s, update_frequency: val }))}
                            disabled={!state.is_active}
                        >
                            <SelectTrigger className="h-9 text-sm border-gray-200 focus:ring-teal-400 disabled:opacity-50">
                                <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                                {FREQUENCY_OPTIONS.map(opt => (
                                    <SelectItem key={opt.value} value={opt.value} className="text-sm">
                                        {opt.label}
                                    </SelectItem>
                                ))}
                            </SelectContent>
                        </Select>
                    </div>

                    <div className="flex-shrink-0 mt-5">
                        <Button
                            onClick={handleSave}
                            disabled={isSaving}
                            size="sm"
                            className="bg-teal-600 hover:bg-teal-700 text-white text-sm px-5"
                        >
                            {isSaving ? "Saving..." : "Save"}
                        </Button>
                    </div>
                </div>

                {/* Status row */}
                <div className="flex items-center justify-between pt-1 border-t border-gray-50">
                    <div className="flex items-center gap-2 text-xs text-gray-500">
                        <Clock className="h-3.5 w-3.5" />
                        <span>Last sync: <span className="font-medium text-gray-700">{formatLastSync(state.last_sync_at)}</span></span>
                    </div>

                    <Badge
                        className={
                            isRunning
                                ? "bg-blue-50 text-blue-600 border border-blue-200 gap-1 animate-pulse"
                                : state.is_active
                                    ? "bg-emerald-50 text-emerald-600 border border-emerald-200 gap-1"
                                    : "bg-gray-100 text-gray-500 gap-1"
                        }
                    >
                        {isRunning
                            ? <><RefreshCw className="h-3 w-3 animate-spin" /> Running</>
                            : state.is_active
                                ? <><CheckCircle2 className="h-3 w-3" /> Idle</>
                                : "Paused"}
                    </Badge>
                </div>

                {/* Save confirmation */}
                {savedMsg && (
                    <p className={`text-xs font-medium ${savedMsg.includes("success") ? "text-emerald-600" : "text-red-500"}`}>
                        {savedMsg}
                    </p>
                )}
            </CardContent>
        </Card>
    );
}
