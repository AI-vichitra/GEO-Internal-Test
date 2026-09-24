"use client";

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { Plus, Layout, Calendar, Globe, Briefcase, ChevronRight, Search, Trash2, CalendarClock, Clock, Layers } from "lucide-react";
import { useAuth } from "@/contexts/AuthContext";
import { getAuthToken } from "@/lib/queryClient";
import {
    AlertDialog,
    AlertDialogAction,
    AlertDialogCancel,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Switch } from "@/components/ui/switch";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "https://api.optimiseurbrand.tech";

const FREQUENCY_OPTIONS = [
    { value: "1h",  label: "Every 1 hour" },
    { value: "6h",  label: "Every 6 hours" },
    { value: "12h", label: "Every 12 hours" },
    { value: "24h", label: "Every 24 hours (Daily)" },
    { value: "48h", label: "Every 48 hours" },
    { value: "7d",  label: "Every 7 days (Weekly)" },
    { value: "14d", label: "Every 14 days" },
    { value: "30d", label: "Every 30 days (Monthly)" },
];


interface Project {
    id: string;
    name: string;
    website_url?: string;
    industry?: string;
    update_frequency: string;
    is_active: boolean;
    sync_status?: string;   // 'idle' | 'running'
    created_at: string;
    last_sync_at?: string;
}

interface ProjectsWindowProps {
    onSelectProject: (projectId: string) => void;
    onCreateProject: () => void;
}



export function ProjectsWindow({ onSelectProject, onCreateProject }: ProjectsWindowProps) {
    const { subscription, planLimits } = useAuth();
    const [projects, setProjects] = useState<Project[]>([]);
    const [isLoading, setIsLoading] = useState(true);
    const [searchQuery, setSearchQuery] = useState("");
    const [projectToDelete, setProjectToDelete] = useState<string | null>(null);
    // Per-project scheduler local state: { is_active, update_frequency, saving, saved }
    const [schedulerState, setSchedulerState] = useState<Record<string, {
        is_active: boolean;
        update_frequency: string;
        saving: boolean;
        saved: boolean;
    }>>({});

    const planName = subscription.subscription_plan?.toUpperCase() || "FREE";
    const isLimitReached = projects.length >= planLimits.max_projects;

    useEffect(() => {
        fetchProjects();
    }, []);

    // ... (rest as is)
    const fetchProjects = async () => {
        setIsLoading(true);
        try {
            const token = getAuthToken();
            const response = await fetch(`${API_BASE_URL}/api/projects`, {
                headers: { "Authorization": `Bearer ${token}` },
                credentials: "include"
            });
            if (response.ok) {
                const data = await response.json();
                setProjects(data.projects || []);
            }
        } catch (error) {
            console.error("Error fetching projects:", error);
        } finally {
            setIsLoading(false);
        }
    };

    // Sync schedulerState when projects load
    useEffect(() => {
        setSchedulerState(prev => {
            const next = { ...prev };
            projects.forEach(p => {
                if (!next[p.id]) {
                    next[p.id] = {
                        is_active: p.is_active,
                        update_frequency: p.update_frequency || "24h",
                        saving: false,
                        saved: false,
                    };
                }
            });
            return next;
        });
    }, [projects]);

    const filteredProjects = projects.filter(p =>
        p.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        p.industry?.toLowerCase().includes(searchQuery.toLowerCase())
    );

    const patchScheduler = (projectId: string, patch: Partial<typeof schedulerState[string]>) =>
        setSchedulerState(prev => ({ ...prev, [projectId]: { ...prev[projectId], ...patch } }));

    const saveScheduleSettings = useCallback(async (e: React.MouseEvent | React.FormEvent, projectId: string) => {
        e.stopPropagation();
        const s = schedulerState[projectId];
        if (!s || s.saving) return;
        patchScheduler(projectId, { saving: true, saved: false });
        try {
            const token = getAuthToken();
            const res = await fetch(`${API_BASE_URL}/api/projects/${projectId}`, {
                method: "PUT",
                headers: { "Content-Type": "application/json", "Authorization": `Bearer ${token}` },
                credentials: "include",
                body: JSON.stringify({ is_active: s.is_active, update_frequency: s.update_frequency }),
            });
            if (!res.ok) throw new Error("Failed");
            // Reflect saved state in projects list
            setProjects(prev => prev.map(p => p.id === projectId
                ? { ...p, is_active: s.is_active, update_frequency: s.update_frequency }
                : p
            ));
            patchScheduler(projectId, { saving: false, saved: true });
            setTimeout(() => patchScheduler(projectId, { saved: false }), 2000);
        } catch {
            patchScheduler(projectId, { saving: false });
        }
    }, [schedulerState]);

    const handleDeleteProject = async () => {
        if (!projectToDelete) return;

        try {
            const token = getAuthToken();
            const response = await fetch(`${API_BASE_URL}/api/projects/${projectToDelete}`, {
                method: "DELETE",
                headers: { "Authorization": `Bearer ${token}` },
                credentials: "include"
            });

            if (response.ok) {
                setProjects(prev => prev.filter(p => p.id !== projectToDelete));
                setProjectToDelete(null);
            } else {
                console.error("Failed to delete project");
            }
        } catch (error) {
            console.error("Error deleting project:", error);
        }
    };

    if (isLoading) {
        return (
            <div className="flex flex-col items-center justify-center min-h-[400px] gap-4">
                <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-teal-500"></div>
                <p className="text-gray-500 font-medium">Loading your projects...</p>
            </div>
        );
    }

    return (
        <div className="space-y-8 animate-in fade-in slide-in-from-bottom-4 duration-500">
            <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
                <div>
                    <h1 className="text-3xl font-bold tracking-tight text-gray-900">Brand Projects</h1>
                    <p className="text-gray-500 mt-1">Manage and monitor your brand visibility across all your projects.</p>
                </div>
                <div className="flex flex-wrap items-center gap-3 w-full sm:w-auto justify-between sm:justify-end">
                    {/* Plan & Project Limits Tracker Element */}
                    <div className="flex items-center gap-3 px-3.5 py-2 rounded-xl bg-white border border-gray-200/90 shadow-sm text-xs">
                        <div className="flex items-center gap-2">
                            <span className="flex h-2 w-2 relative">
                                <span className={`animate-ping absolute inline-flex h-full w-full rounded-full opacity-75 ${isLimitReached ? "bg-amber-400" : "bg-teal-400"}`}></span>
                                <span className={`relative inline-flex rounded-full h-2 w-2 ${isLimitReached ? "bg-amber-500" : "bg-teal-500"}`}></span>
                            </span>
                            <span className="font-semibold text-gray-900 capitalize tracking-wide">
                                {planName.toLowerCase()} Plan
                            </span>
                        </div>
                        <div className="h-3.5 w-px bg-gray-200" />
                        <div className="flex items-center gap-1.5">
                            <span className="text-gray-500">Projects:</span>
                            <span className={`font-bold ${isLimitReached ? "text-amber-600" : "text-gray-900"}`}>
                                {projects.length}
                            </span>
                            <span className="text-gray-400">/</span>
                            <span className="text-gray-600 font-medium">{planLimits.max_projects}</span>
                        </div>
                        {/* Mini progress meter */}
                        <div className="w-16 h-1.5 bg-gray-100 rounded-full overflow-hidden hidden sm:block">
                            <div 
                                className={`h-full rounded-full transition-all duration-300 ${isLimitReached ? "bg-amber-500" : "bg-teal-500"}`}
                                style={{ width: `${Math.min(100, Math.round((projects.length / Math.max(1, planLimits.max_projects)) * 100))}%` }}
                            />
                        </div>
                        {isLimitReached && (
                            <Link 
                                href="/pricing" 
                                className="ml-0.5 text-[11px] font-semibold text-teal-600 hover:text-teal-700 underline underline-offset-2 transition-colors"
                            >
                                Upgrade
                            </Link>
                        )}
                    </div>

                    <Button
                        onClick={onCreateProject}
                        className={`shadow-md transition-all ${isLimitReached ? "bg-gray-200 text-gray-400 cursor-not-allowed hover:bg-gray-200" : "bg-teal-500 text-white hover:bg-teal-600 hover:scale-105"}`}
                        disabled={isLimitReached}
                    >
                        <Plus className="h-4 w-4 mr-2" />
                        Create New Project
                    </Button>
                </div>
            </div>

            <div className="relative">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400" />
                <Input
                    placeholder="Search projects by name or industry..."
                    className="pl-10 h-12 bg-white border-gray-200 text-gray-900 placeholder:text-gray-400 shadow-sm focus:border-teal-400 focus:ring-teal-400/20"
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                />
            </div>

            {filteredProjects.length === 0 ? (
                <Card className="border-dashed border-2 border-gray-200 py-12 bg-gray-50/50">
                    <CardContent className="flex flex-col items-center justify-center text-center space-y-4">
                        <div className="h-16 w-16 rounded-full bg-gray-100 flex items-center justify-center">
                            <Layout className="h-8 w-8 text-gray-400" />
                        </div>
                        <div className="max-w-xs">
                            <h3 className="text-lg font-semibold text-gray-900">No projects found</h3>
                            <p className="text-gray-500 mt-2">
                                {searchQuery ? "Try adjusting your search terms." : "You haven't created any brand projects yet. Get started by creating your first one."}
                            </p>
                        </div>
                        {!searchQuery && (
                            <Button onClick={onCreateProject} variant="outline" className="mt-4 border-gray-200 text-gray-600 hover:bg-gray-50 hover:text-gray-900">
                                Create My First Project
                            </Button>
                        )}
                    </CardContent>
                </Card>
            ) : (
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                    {filteredProjects.map((project) => (
                        <Card
                            key={project.id}
                            className="group hover:shadow-lg transition-all duration-300 border-gray-100 bg-white overflow-hidden cursor-pointer"
                            onClick={() => onSelectProject(project.id)}
                        >
                            <CardHeader className="pb-4">
                                <div className="flex justify-between items-start">
                                    <div className="h-12 w-12 rounded-xl bg-gray-50 flex items-center justify-center text-gray-500 group-hover:bg-teal-50 group-hover:text-teal-600 transition-colors duration-300 border border-gray-100">
                                        <Briefcase className="h-6 w-6" />
                                    </div>
                                    {/* Scheduler popover button */}
                                    <Popover>
                                        <PopoverTrigger asChild>
                                            <button
                                                onClick={e => e.stopPropagation()}
                                                className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border text-xs font-medium transition-all duration-200 ${
                                                    project.is_active
                                                        ? "bg-teal-50 border-teal-200 text-teal-700 hover:bg-teal-100"
                                                        : "bg-gray-50 border-gray-200 text-gray-500 hover:bg-gray-100"
                                                }`}
                                            >
                                                <CalendarClock className="h-3.5 w-3.5" />
                                                {project.is_active ? `Every ${project.update_frequency}` : "Schedule"}
                                            </button>
                                        </PopoverTrigger>
                                        <PopoverContent
                                            className="w-64 p-0 shadow-xl border border-gray-100 rounded-xl overflow-hidden"
                                            align="end"
                                            onClick={e => e.stopPropagation()}
                                        >
                                            {/* Header */}
                                            <div className="bg-gradient-to-r from-teal-500 to-emerald-500 px-4 py-3">
                                                <p className="text-white text-sm font-semibold">Auto-Sync Schedule</p>
                                                <p className="text-teal-100 text-xs mt-0.5">Automatically re-run analysis on a timer</p>
                                            </div>

                                            <div className="p-4 space-y-4">
                                                {/* ON/OFF Toggle */}
                                                <div className="flex items-center justify-between">
                                                    <div>
                                                        <p className="text-sm font-medium text-gray-800">Auto-Sync</p>
                                                        <p className="text-xs text-gray-400">
                                                            {schedulerState[project.id]?.is_active ? "Enabled" : "Disabled"}
                                                        </p>
                                                    </div>
                                                    <Switch
                                                        checked={schedulerState[project.id]?.is_active ?? project.is_active}
                                                        onCheckedChange={val => patchScheduler(project.id, { is_active: val })}
                                                        className="data-[state=checked]:bg-teal-500"
                                                    />
                                                </div>

                                                {/* Frequency selector */}
                                                <div className="space-y-1.5">
                                                    <label className="text-xs font-medium text-gray-500 flex items-center gap-1">
                                                        <Clock className="h-3 w-3" /> Interval
                                                    </label>
                                                    <Select
                                                        value={schedulerState[project.id]?.update_frequency ?? project.update_frequency}
                                                        onValueChange={val => patchScheduler(project.id, { update_frequency: val })}
                                                        disabled={!(schedulerState[project.id]?.is_active ?? project.is_active)}
                                                    >
                                                        <SelectTrigger className="h-8 text-xs border-gray-200 focus:ring-teal-400">
                                                            <SelectValue />
                                                        </SelectTrigger>
                                                        <SelectContent>
                                                            {FREQUENCY_OPTIONS.map(opt => (
                                                                <SelectItem key={opt.value} value={opt.value} className="text-xs">
                                                                    {opt.label}
                                                                </SelectItem>
                                                            ))}
                                                        </SelectContent>
                                                    </Select>
                                                </div>

                                                {/* Save button */}
                                                <Button
                                                    size="sm"
                                                    className="w-full bg-teal-600 hover:bg-teal-700 text-white text-xs h-8"
                                                    disabled={schedulerState[project.id]?.saving}
                                                    onClick={e => saveScheduleSettings(e, project.id)}
                                                >
                                                    {schedulerState[project.id]?.saving
                                                        ? "Saving..."
                                                        : schedulerState[project.id]?.saved
                                                            ? "✓ Saved!"
                                                            : "Save Settings"}
                                                </Button>
                                            </div>
                                        </PopoverContent>
                                    </Popover>

                                </div>
                                <CardTitle className="mt-4 text-xl text-gray-900 group-hover:text-teal-600 transition-colors">{project.name}</CardTitle>
                                <CardDescription className="flex items-center gap-1 mt-1 text-gray-500">
                                    <Globe className="h-3 w-3" />
                                    {project.website_url || "No website link"}
                                </CardDescription>
                            </CardHeader>
                            <CardContent className="pb-4 space-y-3">
                                <div className="flex items-center text-sm text-gray-600 gap-2">
                                    <Calendar className="h-4 w-4 text-gray-400" />
                                    <span>
                                        {project.is_active
                                            ? `Auto-syncs every ${project.update_frequency}`
                                            : `Syncs every ${project.update_frequency}`}
                                    </span>
                                </div>
                                {project.industry && (
                                    <div className="flex items-center text-sm text-gray-600 gap-2">
                                        <div className="h-1 w-1 rounded-full bg-gray-400 ml-1.5 mr-1" />
                                        <span>{project.industry}</span>
                                    </div>
                                )}
                            </CardContent>
                            <CardFooter className="pt-4 border-t border-gray-50 bg-gray-50/30 group-hover:bg-white transition-colors relative">
                                <div className="flex justify-between items-center w-full">
                                    <span className="text-xs text-gray-400">
                                        Created {new Date(project.created_at).toLocaleDateString()}
                                    </span>
                                    <div className="flex items-center gap-3">
                                        <Button
                                            variant="ghost"
                                            size="icon"
                                            className="h-8 w-8 text-gray-400 hover:text-red-600 hover:bg-red-50"
                                            onClick={(e) => {
                                                e.stopPropagation();
                                                setProjectToDelete(project.id);
                                            }}
                                        >
                                            <Trash2 className="h-4 w-4" />
                                        </Button>
                                        <div className="flex items-center text-sm font-semibold text-teal-600 opacity-0 group-hover:opacity-100 translate-x-4 group-hover:translate-x-0 transition-all duration-300">
                                            Open Dashboard
                                            <ChevronRight className="h-4 w-4 ml-1" />
                                        </div>
                                    </div>
                                </div>
                            </CardFooter>
                        </Card>
                    ))}
                </div>
            )}


            <AlertDialog open={!!projectToDelete} onOpenChange={(open) => !open && setProjectToDelete(null)}>
                <AlertDialogContent className="bg-white border-gray-200">
                    <AlertDialogHeader>
                        <AlertDialogTitle>Are you sure that you want to delete this project completely?</AlertDialogTitle>
                        <AlertDialogDescription>
                            This action cannot be undone. This will permanently delete your project and remove all data associated with it from our servers.
                        </AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                        <AlertDialogCancel>Cancel</AlertDialogCancel>
                        <AlertDialogAction onClick={handleDeleteProject} className="bg-red-600 hover:bg-red-700 text-white">
                            Delete Project
                        </AlertDialogAction>
                    </AlertDialogFooter>
                </AlertDialogContent>
            </AlertDialog>
        </div>
    );
}
