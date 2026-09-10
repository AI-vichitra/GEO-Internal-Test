import { Button } from "@/components/ui/button";
import { Download } from "lucide-react";
import { useState } from "react";
import jsPDF from "jspdf";
import autoTable from "jspdf-autotable";
import type { AnalysisResults as AnalysisResultsType } from "@shared/schema";


// ─── Color Palette ────────────────────────────────────────────────────────────
const C = {
  teal:      [13, 148, 136]  as [number, number, number],
  tealLight: [204, 241, 238] as [number, number, number],
  dark:      [17, 24, 39]    as [number, number, number],
  mid:       [75, 85, 99]    as [number, number, number],
  muted:     [156, 163, 175] as [number, number, number],
  subtle:    [243, 244, 246] as [number, number, number],
  border:    [229, 231, 235] as [number, number, number],
  white:     [255, 255, 255] as [number, number, number],
  green:     [16, 185, 129]  as [number, number, number],
  amber:     [245, 158, 11]  as [number, number, number],
  red:       [239, 68, 68]   as [number, number, number],
  blue:      [59, 130, 246]  as [number, number, number],
  purple:    [139, 92, 246]  as [number, number, number],
};

interface PDFReportButtonProps {
  results: AnalysisResultsType;
  sessionId: string;
}

export function PDFReportButton({ results, sessionId }: PDFReportButtonProps) {
  const [isGenerating, setIsGenerating] = useState(false);


  // ─── Helpers ───────────────────────────────────────────────────────────────

  const loadImageAsBase64 = (path: string): Promise<string> =>
    new Promise((resolve, reject) => {
      const img = new Image();
      img.crossOrigin = "Anonymous";
      img.src = path;
      img.onload = () => {
        const canvas = document.createElement("canvas");
        canvas.width = img.width;
        canvas.height = img.height;
        const ctx = canvas.getContext("2d");
        if (!ctx) return reject("Canvas error");
        ctx.drawImage(img, 0, 0);
        resolve(canvas.toDataURL("image/png"));
      };
      img.onerror = reject;
    });

  const sanitizeText = (text: string | undefined | null, maxLen = 9999): string => {
    if (!text) return "";
    const patterns = [
      /An AI Overview is not available for this search/gi,
      /Can(?:'t| not) generate an AI overview right now(?:\.|)\s*Try again later(?:\.|)/gi,
      /AI Overview/gi,
      /Listen\s*Pause/gi,
    ];
    let cleaned = text;
    for (const p of patterns) cleaned = cleaned.replace(p, "");
    cleaned = cleaned.replace(/\s+/g, " ").trim();
    return cleaned.length > maxLen ? cleaned.substring(0, maxLen - 3) + "..." : cleaned;
  };

  // Compute deduplicated brand rank from brand_scores
  const computeBrandRank = () => {
    if (!results.brand_scores || results.brand_scores.length === 0) return { rank: 0, totalBrands: 0 };
    const deduped: Record<string, { positions: number[]; vis: number[] }> = {};
    results.brand_scores.forEach((s: any) => {
      const k = s.brand.toLowerCase();
      if (!deduped[k]) deduped[k] = { positions: [], vis: [] };
      if (s.average_position > 0) deduped[k].positions.push(s.average_position);
      deduped[k].vis.push(s.visibility_score || 0);
    });
    const sorted = Object.entries(deduped)
      .map(([brand, d]) => ({
        brand,
        avgPos: d.positions.length ? d.positions.reduce((a, b) => a + b, 0) / d.positions.length : 0,
      }))
      .sort((a, b) => {
        if (a.avgPos === 0) return 1;
        if (b.avgPos === 0) return -1;
        return a.avgPos - b.avgPos;
      });
    const idx = sorted.findIndex(m => m.brand === results.brand_name.toLowerCase());
    return { rank: idx >= 0 ? idx + 1 : 0, totalBrands: sorted.length };
  };

  // ─── Main Generator ────────────────────────────────────────────────────────

  const generatePDF = async () => {
    setIsGenerating(true);
    try {
      const pdf = new jsPDF("p", "mm", "a4");
      const PW = pdf.internal.pageSize.getWidth();
      const PH = pdf.internal.pageSize.getHeight();
      const ML = 18, MR = 18;
      const CW = PW - ML - MR;
      let yPos = 0;

      const { rank: mainBrandRank, totalBrands } = computeBrandRank();
      const mentionRate = results.num_prompts > 0
        ? ((results.average_mentions || 0) / results.num_prompts * 100).toFixed(0)
        : "0";

      // ── Shared: page header ─────────────────────────────────────────────────
      const pageHeader = (title: string, subtitle?: string) => {
        pdf.setFillColor(...C.teal);
        pdf.rect(0, 0, PW, 10, "F");
        pdf.setFillColor(...C.teal);
        pdf.rect(0, 10, 4, 24, "F");
        pdf.setFont("helvetica", "bold");
        pdf.setFontSize(17);
        pdf.setTextColor(...C.dark);
        pdf.text(title, ML + 2, 25);
        if (subtitle) {
          pdf.setFont("helvetica", "normal");
          pdf.setFontSize(8.5);
          pdf.setTextColor(...C.muted);
          pdf.text(subtitle, ML + 2, 31);
        }
        pdf.setDrawColor(...C.border);
        pdf.setLineWidth(0.3);
        pdf.line(ML, 36, PW - MR, 36);
        yPos = 43;
      };

      // ── Shared: stat card ───────────────────────────────────────────────────
      const statCard = (
        x: number, y: number, w: number, h: number,
        label: string, value: string,
        color: [number, number, number] = C.teal
      ) => {
        pdf.setFillColor(...C.subtle);
        pdf.setDrawColor(...C.border);
        pdf.setLineWidth(0.3);
        pdf.roundedRect(x, y, w, h, 2, 2, "FD");
        pdf.setFillColor(...color);
        pdf.roundedRect(x, y, w, 1.5, 0.5, 0.5, "F");
        pdf.setFont("helvetica", "normal");
        pdf.setFontSize(7.5);
        pdf.setTextColor(...C.muted);
        pdf.text(label.toUpperCase(), x + 5, y + 9);
        pdf.setFont("helvetica", "bold");
        pdf.setFontSize(18);
        pdf.setTextColor(...C.dark);
        pdf.text(value, x + 5, y + 20);
      };

      // ── Shared: add footers ─────────────────────────────────────────────────
      const addFooters = () => {
        const total = pdf.getNumberOfPages();
        for (let i = 2; i <= total; i++) {
          pdf.setPage(i);
          pdf.setDrawColor(...C.border);
          pdf.setLineWidth(0.3);
          pdf.line(ML, PH - 12, PW - MR, PH - 12);
          pdf.setFontSize(7.5);
          pdf.setFont("helvetica", "normal");
          pdf.setTextColor(...C.muted);
          pdf.text(`GEO Brand Visibility Report  •  ${results.brand_name}`, ML, PH - 7);
          pdf.text(`Page ${i} of ${total}`, PW - MR, PH - 7, { align: "right" });
        }
      };

      // ═══════════════════════════════════════════════════════════════════════
      // PAGE 1 – COVER
      // ═══════════════════════════════════════════════════════════════════════

      // Teal header band
      pdf.setFillColor(...C.teal);
      pdf.rect(0, 0, PW, 55, "F");

      // Logo
      try {
        const logo = await loadImageAsBase64("/logo.png");
        if (logo) pdf.addImage(logo, "PNG", ML, 10, 52, 17);
      } catch { /* skip */ }

      // Date – top right
      pdf.setFont("helvetica", "normal");
      pdf.setFontSize(9);
      pdf.setTextColor(...C.white);
      const dateStr = new Date().toLocaleDateString("en-US", { year: "numeric", month: "long", day: "numeric" });
      pdf.text(dateStr, PW - MR, 18, { align: "right" });

      // Title in band
      pdf.setFont("helvetica", "bold");
      pdf.setFontSize(28);
      pdf.setTextColor(...C.white);
      pdf.text("Brand Visibility", ML, 37);
      pdf.setTextColor(...C.tealLight);
      pdf.text("Analysis Report", ML, 50);

      // Prepared For
      yPos = 68;
      pdf.setFont("helvetica", "normal");
      pdf.setFontSize(9);
      pdf.setTextColor(...C.muted);
      pdf.text("PREPARED FOR", ML, yPos);
      yPos += 7;
      pdf.setFont("helvetica", "bold");
      pdf.setFontSize(26);
      pdf.setTextColor(...C.dark);
      pdf.text(results.brand_name, ML, yPos);
      yPos += 4;
      pdf.setFillColor(...C.teal);
      pdf.rect(ML, yPos, 24, 1.2, "F");
      yPos += 12;

      // Details
      const details: [string, string][] = [];
      if (results.product_name) details.push(["Product / Service", results.product_name]);
      if (results.industry)     details.push(["Industry", results.industry]);
      if (results.website_url)  details.push(["Website", results.website_url]);
      details.forEach(([lbl, val]) => {
        pdf.setFont("helvetica", "normal");
        pdf.setFontSize(8.5);
        pdf.setTextColor(...C.muted);
        pdf.text(lbl, ML, yPos);
        pdf.setFont("helvetica", "bold");
        pdf.setTextColor(...C.mid);
        pdf.text(val, ML + 40, yPos);
        yPos += 7;
      });

      // 4 stat cards
      yPos = 150;
      const cardW = (CW - 9) / 4;
      const cardH = 30;
      const coverStats = [
        { label: "Analyzed Prompts", value: String(results.num_prompts || 0),                             color: C.teal  },
        { label: "Mention Rate",      value: `${mentionRate}%`,                                           color: C.blue  },
        { label: "Overall Rank",      value: mainBrandRank ? `#${mainBrandRank}` : "—",                   color: C.amber },
        { label: "Visibility Score",  value: `${(results.average_visibility_score || 0).toFixed(1)}%`,   color: C.green },
      ];
      coverStats.forEach((s, i) => {
        statCard(ML + i * (cardW + 3), yPos, cardW, cardH, s.label, s.value, s.color as [number, number, number]);
      });

      // Bottom meta strip
      const bottomY = PH - 30;
      pdf.setFillColor(...C.subtle);
      pdf.rect(0, bottomY, PW, 30, "F");
      pdf.setFont("helvetica", "normal");
      pdf.setFontSize(8);
      pdf.setTextColor(...C.muted);
      pdf.text("SESSION ID", ML, bottomY + 10);
      pdf.text("GENERATED BY", ML + 90, bottomY + 10);
      pdf.setFont("helvetica", "bold");
      pdf.setFontSize(8);
      pdf.setTextColor(...C.mid);
      pdf.text(sessionId, ML, bottomY + 18);
      pdf.text("GEO — AI Visibility Intelligence Platform", ML + 90, bottomY + 18);

      // ═══════════════════════════════════════════════════════════════════════
      // PAGE 2 – EXECUTIVE SUMMARY
      // ═══════════════════════════════════════════════════════════════════════
      pdf.addPage();
      pageHeader("Executive Summary", `Brand: ${results.brand_name}  •  Analysis Date: ${dateStr}`);

      // 4 metric cards
      const mc_w = (CW - 6) / 4;
      const mc_h = 32;
      const metricCards = [
        { label: "Total Prompts",   value: String(results.num_prompts || 0),                             color: C.teal  },
        { label: "Visibility",      value: `${(results.average_visibility_score || 0).toFixed(1)}%`,    color: C.green },
        { label: "Avg. Position",   value: results.average_position ? results.average_position.toFixed(1) : "—", color: C.blue  },
        { label: "Mention Rate",    value: `${mentionRate}%`,                                            color: C.amber },
      ];
      metricCards.forEach((m, i) => {
        statCard(ML + i * (mc_w + 2), yPos, mc_w, mc_h, m.label, m.value, m.color as [number, number, number]);
      });
      yPos += mc_h + 12;

      // Key Findings
      pdf.setFont("helvetica", "bold");
      pdf.setFontSize(11);
      pdf.setTextColor(...C.dark);
      pdf.text("Key Findings", ML, yPos);
      yPos += 9;

      const insights: string[] = [
        `Your brand appeared in ${mentionRate}% of the ${results.num_prompts || 0} generative AI responses analyzed.`,
        `Average brand position when mentioned: ${results.average_position ? results.average_position.toFixed(1) : "N/A"}.`,
        `Overall visibility health score: ${(results.average_visibility_score || 0).toFixed(1)}%, reflecting mention frequency and ranking position.`,
      ];
      if (mainBrandRank) {
        insights.push(`Competitive rank among ${totalBrands} tracked brands: #${mainBrandRank}.`);
      }
      if (results.selected_llms && results.selected_llms.length > 0) {
        insights.push(`Analysis run across ${results.selected_llms.length} AI model${results.selected_llms.length > 1 ? "s" : ""}: ${results.selected_llms.join(", ")}.`);
      }

      pdf.setFont("helvetica", "normal");
      pdf.setFontSize(9.5);
      insights.forEach((insight) => {
        pdf.setFillColor(...C.teal);
        pdf.circle(ML + 2.5, yPos - 1.5, 1.5, "F");
        pdf.setTextColor(...C.mid);
        const lines = pdf.splitTextToSize(insight, CW - 10);
        pdf.text(lines, ML + 8, yPos);
        yPos += lines.length * 5.5 + 4;
      });

      // Model Distribution table
      if (results.model_usage && results.model_usage.length > 0) {
        yPos += 4;
        pdf.setFont("helvetica", "bold");
        pdf.setFontSize(11);
        pdf.setTextColor(...C.dark);
        pdf.text("Model Distribution", ML, yPos);
        yPos += 6;

        const modelData = results.model_usage.map((m: any) => [
          m.model || "Unknown",
          String(m.count || 0),
          `${(m.percentage || 0).toFixed(1)}%`,
        ]);

        autoTable(pdf, {
          startY: yPos,
          head: [["AI Model", "Responses", "Share"]],
          body: modelData,
          theme: "plain",
          headStyles: { fillColor: C.teal, textColor: 255, fontStyle: "bold", cellPadding: 4, fontSize: 9 },
          bodyStyles: { textColor: C.mid, cellPadding: 4, fontSize: 9 },
          alternateRowStyles: { fillColor: C.subtle },
          columnStyles: { 1: { halign: "center" }, 2: { halign: "center" } },
          margin: { left: ML, right: MR },
        });
        yPos = (pdf as any).lastAutoTable.finalY + 8;
      }

      // ═══════════════════════════════════════════════════════════════════════
      // PAGE 3 – COMPETITIVE LANDSCAPE
      // ═══════════════════════════════════════════════════════════════════════
      const hasCompetitors = results.brand_scores && results.brand_scores.length > 0;
      const hasSoV = results.share_of_voice && results.share_of_voice.length > 0;

      if (hasCompetitors || hasSoV) {
        pdf.addPage();
        pageHeader("Competitive Landscape", "Brand rankings and share of voice analysis");

        if (hasCompetitors) {
          pdf.setFont("helvetica", "bold");
          pdf.setFontSize(11);
          pdf.setTextColor(...C.dark);
          pdf.text("Brand Rankings", ML, yPos);
          yPos += 6;

          const deduped: Record<string, { brand: string; positions: number[]; vis: number[]; mr: number[] }> = {};
          results.brand_scores.forEach((s: any) => {
            const k = s.brand.toLowerCase();
            if (!deduped[k]) deduped[k] = { brand: s.brand, positions: [], vis: [], mr: [] };
            if (s.average_position > 0) deduped[k].positions.push(s.average_position);
            deduped[k].vis.push(s.visibility_score || 0);
            deduped[k].mr.push(s.mention_rate || 0);
          });

          const rankRows = Object.values(deduped)
            .map(d => ({
              brand: d.brand,
              avgPos: d.positions.length ? d.positions.reduce((a, b) => a + b, 0) / d.positions.length : 0,
              vis: d.vis.reduce((a, b) => a + b, 0) / d.vis.length,
              mr: d.mr.reduce((a, b) => a + b, 0) / d.mr.length,
            }))
            .sort((a, b) => {
              if (a.avgPos === 0) return 1;
              if (b.avgPos === 0) return -1;
              return a.avgPos - b.avgPos;
            });

          const competitorRows = rankRows.map((r, idx) => [
            `#${idx + 1}`,
            r.brand,
            r.avgPos > 0 ? r.avgPos.toFixed(1) : "—",
            `${r.vis.toFixed(1)}%`,
            `${(r.mr * 100).toFixed(0)}%`,
          ]);

          autoTable(pdf, {
            startY: yPos,
            head: [["Rank", "Brand / Competitor", "Avg. Position", "Visibility", "Mention Rate"]],
            body: competitorRows,
            theme: "plain",
            headStyles: { fillColor: C.dark, textColor: 255, fontStyle: "bold", cellPadding: 4, fontSize: 9 },
            bodyStyles: { textColor: C.mid, cellPadding: 4, fontSize: 9 },
            alternateRowStyles: { fillColor: C.subtle },
            didParseCell: (data: any) => {
              if (data.section === "body") {
                const rowBrand = competitorRows[data.row.index]?.[1];
                if (rowBrand && rowBrand.toLowerCase() === results.brand_name.toLowerCase()) {
                  data.cell.styles.fontStyle = "bold";
                  data.cell.styles.textColor = C.teal;
                }
              }
            },
            columnStyles: {
              0: { cellWidth: 15, halign: "center" },
              2: { halign: "center" },
              3: { halign: "center" },
              4: { halign: "center" },
            },
            margin: { left: ML, right: MR },
          });
          yPos = (pdf as any).lastAutoTable.finalY + 12;
        }

        if (hasSoV) {
          if (yPos > PH - 80) {
            pdf.addPage();
            pageHeader("Competitive Landscape (cont.)", "Share of Voice");
          }

          pdf.setFont("helvetica", "bold");
          pdf.setFontSize(11);
          pdf.setTextColor(...C.dark);
          pdf.text("Share of Voice", ML, yPos);
          yPos += 6;

          const sovMap = new Map<string, any>();
          results.share_of_voice.forEach((item: any) => {
            sovMap.set(item.brand.toLowerCase().trim(), item);
          });
          const sovRows = Array.from(sovMap.values())
            .sort((a: any, b: any) => b.percentage - a.percentage)
            .map((item: any, idx) => [
              idx + 1,
              item.brand || "Unknown",
              `${(item.percentage || 0).toFixed(1)}%`,
              String(item.mention_count || 0),
            ]);

          autoTable(pdf, {
            startY: yPos,
            head: [["Rank", "Brand", "Share of Voice", "Mentions"]],
            body: sovRows,
            theme: "plain",
            headStyles: { fillColor: C.teal, textColor: 255, fontStyle: "bold", cellPadding: 4, fontSize: 9 },
            bodyStyles: { textColor: C.mid, cellPadding: 4, fontSize: 9 },
            alternateRowStyles: { fillColor: C.subtle },
            columnStyles: {
              0: { cellWidth: 15, halign: "center" },
              2: { halign: "center" },
              3: { halign: "center" },
            },
            margin: { left: ML, right: MR },
          });
        }
      }

      // ═══════════════════════════════════════════════════════════════════════
      // PAGE 4 – SOURCE ANALYSIS
      // ═══════════════════════════════════════════════════════════════════════
      if (results.domain_citations && results.domain_citations.length > 0) {
        pdf.addPage();
        pageHeader("Source Analysis", "Top domains cited by AI models in their responses");

        pdf.setFont("helvetica", "normal");
        pdf.setFontSize(9.5);
        pdf.setTextColor(...C.mid);
        pdf.text(
          `The following ${Math.min(results.domain_citations.length, 20)} domains were most frequently cited across all ${results.num_prompts || 0} analyzed prompts.`,
          ML, yPos
        );
        yPos += 10;

        const citationRows = results.domain_citations.slice(0, 20).map((item: any, idx) => [
          idx + 1,
          item.domain || "Unknown",
          String(item.citation_count || 0),
          `${(item.percentage || 0).toFixed(1)}%`,
        ]);

        autoTable(pdf, {
          startY: yPos,
          head: [["#", "Domain", "Citations", "Frequency"]],
          body: citationRows,
          theme: "plain",
          headStyles: { fillColor: C.teal, textColor: 255, fontStyle: "bold", cellPadding: 4, fontSize: 9 },
          bodyStyles: { textColor: C.mid, cellPadding: 4, fontSize: 9 },
          alternateRowStyles: { fillColor: C.subtle },
          columnStyles: {
            0: { cellWidth: 12, halign: "center" },
            2: { halign: "center" },
            3: { halign: "center" },
          },
          margin: { left: ML, right: MR },
        });
      }

      // ═══════════════════════════════════════════════════════════════════════
      // PAGE 5+ – PROMPT ANALYSIS LOG
      // ═══════════════════════════════════════════════════════════════════════
      if (results.llm_responses && results.llm_responses.length > 0) {
        // Deduplicate
        const uniqueMap = new Map<string, any>();
        results.llm_responses.forEach((r: any) => {
          uniqueMap.set(`${r.prompt}|${r.llm_name}`, r);
        });
        const uniqueResponses = Array.from(uniqueMap.values());

        pdf.addPage();
        pageHeader("Prompt Analysis Log", `${uniqueResponses.length} unique prompts analyzed`);

        const promptRows = uniqueResponses.map((r: any, idx) => [
          idx + 1,
          sanitizeText(r.prompt, 160),
          r.llm_name || r.llm_model || "Unknown",
          (r.visibility_score || 0) > 0 ? "Yes" : "No",
          r.visibility_score != null ? `${Number(r.visibility_score).toFixed(0)}%` : "—",
        ]);

        autoTable(pdf, {
          startY: yPos,
          head: [["#", "Prompt", "LLM Model", "Mentioned", "Visibility"]],
          body: promptRows,
          theme: "plain",
          headStyles: { fillColor: C.dark, textColor: 255, fontStyle: "bold", cellPadding: 4, fontSize: 8.5 },
          bodyStyles: { textColor: C.mid, cellPadding: 3.5, fontSize: 8, valign: "middle" },
          alternateRowStyles: { fillColor: C.subtle },
          didParseCell: (data: any) => {
            if (data.section === "body" && data.column.index === 3) {
              data.cell.styles.fontStyle = "bold";
              data.cell.styles.textColor = data.cell.raw === "Yes" ? C.green : C.red;
            }
          },
          columnStyles: {
            0: { cellWidth: 10, halign: "center" },
            1: { cellWidth: "auto" },
            2: { cellWidth: 30 },
            3: { cellWidth: 22, halign: "center" },
            4: { cellWidth: 22, halign: "center" },
          },
          margin: { left: ML, right: MR },
        });

        // ── Detailed AI Response Blocks ────────────────────────────────────
        const detailedResponses = uniqueResponses
          .filter((r: any) => r.response && r.response.length > 20)
          .slice(0, 8);

        if (detailedResponses.length > 0) {
          pdf.addPage();
          pageHeader("AI Response Details", "Full responses from analyzed prompts");

          detailedResponses.forEach((r: any, idx) => {
            if (yPos > PH - 55) {
              pdf.addPage();
              pageHeader("AI Response Details (cont.)");
            }

            // Prompt label bar
            pdf.setFillColor(...C.subtle);
            pdf.setDrawColor(...C.border);
            pdf.setLineWidth(0.3);
            pdf.roundedRect(ML, yPos, CW, 10, 1.5, 1.5, "FD");
            pdf.setFont("helvetica", "bold");
            pdf.setFontSize(8.5);
            pdf.setTextColor(...C.dark);
            pdf.text(`Q${idx + 1}: ${sanitizeText(r.prompt, 120)}`, ML + 4, yPos + 6.5);
            pdf.setFont("helvetica", "normal");
            pdf.setFontSize(7.5);
            pdf.setTextColor(...C.teal);
            pdf.text(r.llm_name || "LLM", PW - MR - 2, yPos + 6.5, { align: "right" });
            yPos += 13;

            // Response body block
            const cleanResponse = sanitizeText(r.response, 600);
            const responseLines = pdf.splitTextToSize(cleanResponse, CW - 8);
            const maxLines = Math.min(responseLines.length, 18);
            const blockH = maxLines * 4.2 + 7;

            pdf.setFillColor(252, 252, 252);
            pdf.setDrawColor(...C.border);
            pdf.setLineWidth(0.2);
            pdf.roundedRect(ML, yPos, CW, blockH, 1.5, 1.5, "FD");
            pdf.setFillColor(...C.teal);
            pdf.rect(ML, yPos, 2.5, blockH, "F");

            pdf.setFont("helvetica", "normal");
            pdf.setFontSize(8);
            pdf.setTextColor(...C.mid);
            pdf.text(responseLines.slice(0, maxLines), ML + 6, yPos + 5.5);
            yPos += blockH + 7;
          });
        }
      }

      // Finalize
      addFooters();
      const fileName = `GEO_Report_${results.brand_name.replace(/\s+/g, "_")}_${new Date().toISOString().split("T")[0]}.pdf`;
      pdf.save(fileName);

    } catch (error) {
      console.error("PDF generation error:", error);
      alert("Failed to generate report. Please try again.");
    } finally {
      setIsGenerating(false);
    }
  };

  return (
    <Button
      onClick={generatePDF}
      disabled={isGenerating}
      className="bg-teal-600 hover:bg-teal-700 text-white gap-2 shadow-md transition-all duration-200"
    >
      <Download className="h-4 w-4" />
      {isGenerating ? "Generating..." : "Download Report"}
    </Button>
  );
}