 { id: "Mistral", name: "Mistral" }
];

interface DashboardPromptManagerProps {
  sessionId: string;
  analyzedPrompts: Set<string>;
  onReanalyze: (selectedPrompts: string[], selectedLLMs: string[]) => void;
  isAnalyzing: boolean;
  cohorts?: any[];
}

export function DashboardPromptManager({
  sessionId,
  analyzedPrompts,
  onReanalyze,
  isAnalyzing,
  cohorts: initialCohorts
}: DashboardPromptManagerProps) {
  const { toast } = useToast();
  const { subscription } = useAuth();

  const planName = subscription.subscription_plan?.toLowerCase() || "free";
  const limits = FRONTEND_PROMPT_LIMITS[planName] || FRONTEND_PROMPT_LIMITS["free"];

  const MAX_SELECTION = limits.max_prompts_per_project;

  const getAvailableLLMs = () => {
    if (planName === "pro plan" || planName === "custom plan") return ALL_LLMS;
    if (planName === "growth plan") return ALL_LLMS.filter(l => l.id !== "Claude");
    return ALL_LLMS.filter(l => l.id !== "ChatGPT" && l.id !== "Claude"); // Lite Plan & free
  };
  const AVAILABLE_LLMS = getAvailableLLMs();

  // State
  const [selectedPrompts, setSelectedPrompts] = useState<Set<string>>(new Set());
  const [customPrompt, setCustomPrompt] = useState("");
  const [expandedCohorts, setExpandedCohorts] = useState<Record<string, boolean>>({});
