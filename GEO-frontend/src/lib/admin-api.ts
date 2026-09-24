import { getAuthToken } from "@/lib/queryClient";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "https://api.optimiseurbrand.tech";

function getAuthHeaders(): Record<string, string> {
  const token = getAuthToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }
  return headers;
}

export async function adminFetch<T = any>(
  endpoint: string,
  options: RequestInit = {}
): Promise<T> {
  const url = `${API_BASE_URL}${endpoint.startsWith("/") ? endpoint : `/${endpoint}`}`;
  
  const response = await fetch(url, {
    ...options,
    credentials: "include",
    headers: {
      ...getAuthHeaders(),
      ...(options.headers || {}),
    },
  });

  if (!response.ok) {
    let errorDetail = "Admin request failed";
    try {
      const errJson = await response.json();
      errorDetail = errJson.detail || errJson.message || errorDetail;
    } catch {
      errorDetail = response.statusText || errorDetail;
    }
    throw new Error(errorDetail);
  }

  return response.json();
}

export const adminApi = {
  get: <T = any>(endpoint: string) => adminFetch<T>(endpoint, { method: "GET" }),
  post: <T = any>(endpoint: string, body: any) =>
    adminFetch<T>(endpoint, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  put: <T = any>(endpoint: string, body: any) =>
    adminFetch<T>(endpoint, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
};

export interface PlanLimits {
  max_projects: number;
  max_prompts_per_project: number;
  max_competitors: number;
}

export interface PlanItem {
  id: string;
  name: string;
  display_name: string;
  description?: string | null;
  badge_text?: string | null;
  monthly_price_paise: number;
  yearly_price_paise: number;
  currency: string;
  features: string[];
  limits: PlanLimits;
  is_active: boolean;
  is_popular: boolean;
  cta_text: string;
  sort_order: number;
  version: number;
  grandfather_existing_subscribers: boolean;
  subscriber_count?: number;
  created_at?: string;
  updated_at?: string;
}

export const plansApi = {
  list: () => adminApi.get<{ plans: PlanItem[] }>("/api/admin/plans"),
  get: (id: string) => adminApi.get<{ plan: PlanItem }>(`/api/admin/plans/${id}`),
  create: (data: Partial<PlanItem>) => adminApi.post<{ success: boolean; plan: PlanItem }>("/api/admin/plans", data),
  update: (id: string, data: Partial<PlanItem> & { expected_version: number; change_reason?: string }) =>
    adminApi.put<{ success: boolean; plan: PlanItem; diff: any }>(`/api/admin/plans/${id}`, data),
};

