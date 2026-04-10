import { useMemo } from "react";
import { SummaryMetrics } from "./summary-metrics";
import { PromptsTable } from "./prompts-table";
import { DualVisibilityCharts } from "./dual-visibility-charts";
import { ShareOfVoiceChart } from "./share-of-voice-chart";
import { DomainCitationsTable } from "./domain-citations-table";
import { PDFReportButton } from "./pdf-report-button";
import { AvgPositionRank } from "./avg-position-rank";
import type { AnalysisResults as AnalysisResultsType } from "@shared/schema";

interface AnalysisResultsProps {
  results: AnalysisResultsType;
  onNewAnalysis: (prompts: string[], llms: string[]) => void;
  isAnalyzing: boolean;
  sessionId: string;
}

export function AnalysisResults({
  results,
  onNewAnalysis,
  isAnalyzing,
  sessionId,
}: AnalysisResultsProps) {

  // Compute the brand's overall rank (same logic as AvgPositionRank widget)
  const mainBrandRank = useMemo(() => {
    const scores = results.brand_scores || [];
    if (!scores.length) return 0;

    // Deduplicate by brand name, take the best (min) rank
    const mergedMap: Record<string, { positions: number[]; minRank: number }> = {};
    scores.forEach((s: any) => {
      const key = s.brand.toLowerCase();
      if (!mergedMap[key]) mergedMap[key] = { positions: [], minRank: s.rank };
      if (s.average_position > 0) mergedMap[key].positions.push(s.average_position);
      mergedMap[key].minRank = Math.min(mergedMap[key].minRank, s.rank);
    });

    const merged = Object.values(mergedMap).map((e: any) => ({
      avgPos: e.positions.length ? e.positions.reduce((a: number, b: number) => a + b, 0) / e.positions.length : 0,
    }));

    const sorted = [...merged].sort((a, b) => {
      if (a.avgPos === 0) return 1;
      if (b.avgPos === 0) return -1;
      return a.avgPos - b.avgPos;
    });

    const brandKey = results.brand_name?.toLowerCase();
    const idx = Object.keys(mergedMap).sort((a, b) => {
      const aPos = mergedMap[a].positions.length
        ? mergedMap[a].positions.reduce((x: number, y: number) => x + y, 0) / mergedMap[a].positions.length
        : 0;
      const bPos = mergedMap[b].positions.length
        ? mergedMap[b].positions.reduce((x: number, y: number) => x + y, 0) / mergedMap[b].positions.length
        : 0;
      if (aPos === 0) return 1;
      if (bPos === 0) return -1;
      return aPos - bPos;
    }).findIndex(k => k === brandKey);
    return idx >= 0 ? idx + 1 : 0;
  }, [results.brand_scores, results.brand_name]);

  const uniqueShareOfVoice = useMemo(() => {
    if (!results.share_of_voice) return [];
    const uniqueMap = new Map();
    results.share_of_voice.forEach(item => {
      const key = item.brand.toLowerCase().trim();
      uniqueMap.set(key, item);
    });
    return Array.from(uniqueMap.values()).sort((a, b) => b.percentage - a.percentage);
  }, [results.share_of_voice]);

  const uniqueResponses = useMemo(() => {
    if (!results.llm_responses) return [];
    const uniqueMap = new Map();
    results.llm_responses.forEach(resp => {
      const key = `${resp.prompt}-${resp.llm_name}`;
      uniqueMap.set(key, resp);
    });
    return Array.from(uniqueMap.values());
  }, [results.llm_responses]);

  return (
    <div className="space-y-6 animate-in fade-in duration-700">

      {/* Header Row */}
      <div className="flex items-center justify-between">
        <h1 className="text-3xl font-bold text-gray-900 tracking-tight">
          {results.brand_name} Analysis
        </h1>
        <PDFReportButton results={results} sessionId={sessionId} />
      </div>

      {/* Summary Metrics */}
      <SummaryMetrics
        totalPrompts={uniqueResponses.length || 0}
        mentionCount={results.average_mentions || 0}
        averageRank={mainBrandRank}
        visibilityScore={results.average_visibility_score || 0}
      />

      {/* Middle Row - 3 Column Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
        <div className="lg:col-span-5">
          <PromptsTable responses={uniqueResponses} />
        </div>
        <div className="lg:col-span-3">
          <AvgPositionRank brandName={results.brand_name} brandScores={results.brand_scores || []} />
        </div>
        <div className="lg:col-span-4">
          <ShareOfVoiceChart shareOfVoice={uniqueShareOfVoice} />
        </div>
      </div>

      {/* Bottom Row - 3 Column Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <DomainCitationsTable citations={results.domain_citations || []} />
        <DualVisibilityCharts brandName={results.brand_name} productName={results.product_name} sessionId={sessionId} />
      </div>
    </div>
  );
}