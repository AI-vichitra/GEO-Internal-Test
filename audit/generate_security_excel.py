import pandas as pd
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

# Define Issues Dataset
issues_data = [
    {
        "Issue ID": "SEC-001",
        "Category": "Authorization (IDOR)",
        "Severity": "Critical",
        "Vulnerability Title": "Unauthenticated Custom Cohort & Prompt Endpoints",
        "Description": "Endpoints /api/analysis/generate-custom-cohort-prompts/{session_id} and /api/analysis/execute-selected-prompts accept session_id with no JWT authentication requirement.",
        "Impact / Risk": "An attacker knowing or enumerating UUIDs could trigger prompt generation or multi-LLM executions on another tenant's project, incurring costs and exposing query parameters.",
        "File & Line Location": "GEO-backend/app.py (Lines 1356, 1450, 1633)",
        "Recommended Fix": "Add user_id: str = Depends(get_current_user) and verify session_metadata.get('user_id') == user_id before processing.",
        "Effort": "Low (1-2 hours)",
        "Priority": "P0 (Immediate)"
    },
    {
        "Issue ID": "SEC-002",
        "Category": "Authentication / Billing",
        "Severity": "Critical",
        "Vulnerability Title": "Client-Supplied user_id in Payment Creation",
        "Description": "Endpoint /api/payments/create-order accepts user_id from the JSON payload body without enforcing JWT authentication or verifying identity against the logged-in token.",
        "Impact / Risk": "A malicious actor could initiate payments or bind subscriptions under arbitrary user IDs, creating invoice discrepancies and subscription hijacking.",
        "File & Line Location": "GEO-backend/app.py (Line 562)",
        "Recommended Fix": "Enforce Depends(get_current_user) dependency and override request.user_id with the authenticated token's user_id.",
        "Effort": "Low (30 mins)",
        "Priority": "P0 (Immediate)"
    },
    {
        "Issue ID": "SEC-003",
        "Category": "Information Disclosure",
        "Severity": "High",
        "Vulnerability Title": "Unauthenticated Session Progress Endpoint",
        "Description": "Endpoint /api/analysis/status/{session_id} returns session execution steps and current progress without requiring user authentication.",
        "Impact / Risk": "Allows unauthorized reconnaissance of active research tasks and brand names undergoing analysis.",
        "File & Line Location": "GEO-backend/app.py (Line 1043)",
        "Recommended Fix": "Add user_id: str = Depends(get_current_user) and validate that the session belongs to user_id before returning status details.",
        "Effort": "Low (30 mins)",
        "Priority": "P1 (High)"
    },
    {
        "Issue ID": "SEC-004",
        "Category": "Network & CORS Security",
        "Severity": "High",
        "Vulnerability Title": "Insecure Plain HTTP & Raw IPs in CORS Allowed Origins",
        "Description": "CORS middleware in backend permits plain HTTP IPs (e.g., http://34.42.234.69, http://geocc.duckdns.org:8000).",
        "Impact / Risk": "Leaves communication vulnerable to Man-In-The-Middle (MITM) attacks and credential eavesdropping over unencrypted transport channels.",
        "File & Line Location": "GEO-backend/app.py (Lines 173-190)",
        "Recommended Fix": "Restrict CORS origins in production strictly to verified HTTPS domains (https://optimiseurbrand.tech). Enforce HTTP-to-HTTPS redirection at reverse proxy.",
        "Effort": "Low (30 mins)",
        "Priority": "P1 (High)"
    },
    {
        "Issue ID": "SEC-005",
        "Category": "Data Privacy & Third-Party Sharing",
        "Severity": "Medium",
        "Vulnerability Title": "LLM Query & Response Tracing to External Collector",
        "Description": "OpenTelemetry exporter streams full prompt and model interaction traces to external collector (collector.agentpaid.io).",
        "Impact / Risk": "Clients with strict NDAs may flag unconsented transmission of brand intelligence or confidential keywords to third-party telemetry vendors.",
        "File & Line Location": "GEO-backend/app.py (Lines 142-160)",
        "Recommended Fix": "Add opt-in telemetry toggle or sanitize sensitive brand identifiers before dispatching spans to external trace collectors.",
        "Effort": "Medium (2-3 hours)",
        "Priority": "P2 (Medium)"
    },
    {
        "Issue ID": "SEC-006",
        "Category": "Access Control (RBAC)",
        "Severity": "Medium",
        "Vulnerability Title": "Single-User Account Model (Missing Organization RBAC)",
        "Description": "Currently, accounts are single-tenant without team/role management (Admin, Editor, Viewer).",
        "Impact / Risk": "Enterprise clients cannot safely invite team members or grant read-only visibility without sharing master credentials.",
        "File & Line Location": "GEO-backend/services/database_manager.py & Schema",
        "Recommended Fix": "Implement workspace_members table with role-based policies (Owner, Editor, Viewer) to support enterprise team governance.",
        "Effort": "High (1-2 days)",
        "Priority": "P2 (Medium)"
    },
    {
        "Issue ID": "SEC-007",
        "Category": "Compliance & Privacy (GDPR/CCPA)",
        "Severity": "Medium",
        "Vulnerability Title": "Absence of Automated Data Retention & Erasure Endpoint",
        "Description": "System retains historical scrape responses indefinitely; no programmatic 'Right to be Forgotten' endpoint exists to purge all customer data on demand.",
        "Impact / Risk": "Non-compliance with GDPR Article 17 (Right to Erasure) and CCPA consumer deletion mandates during enterprise audits.",
        "File & Line Location": "GEO-backend/services/database_manager.py",
        "Recommended Fix": "Implement DELETE /api/user/me endpoint with cascading deletion across users, projects, prompts, and daily_brand_metrics tables.",
        "Effort": "Medium (3-4 hours)",
        "Priority": "P2 (Medium)"
    },
    {
        "Issue ID": "SEC-008",
        "Category": "API Rate Limiting",
        "Severity": "Medium",
        "Vulnerability Title": "Missing Rate Limiting on LLM Execution Endpoints",
        "Description": "Endpoints triggering expensive LLM workflows (/api/analysis/run, /api/cron/process-scheduled-projects) lack client-side IP/user rate limiting.",
        "Impact / Risk": "Potential Denial of Wallet (DoW) or API quota exhaustion if rapid automated requests are dispatched.",
        "File & Line Location": "GEO-backend/app.py (Lines 800, 1337)",
        "Recommended Fix": "Integrate slowapi (FastAPI rate limiter) to throttle LLM-triggering routes (e.g., max 10 requests/minute per user/IP).",
        "Effort": "Medium (2-3 hours)",
        "Priority": "P2 (Medium)"
    },
    {
        "Issue ID": "SEC-009",
        "Category": "Enterprise SSO",
        "Severity": "Low",
        "Vulnerability Title": "Missing Enterprise SAML 2.0 / OIDC Identity Provider Support",
        "Description": "Authentication only supports standard email/password and consumer Google OAuth.",
        "Impact / Risk": "Enterprise clients requiring Okta, Azure AD, or Ping Identity SSO will not be able to enforce centralized identity lifecycle policies.",
        "File & Line Location": "GEO-backend/app.py & GEO-frontend/src/app/login",
        "Recommended Fix": "Integrate SAML/OIDC SSO via Supabase Auth Enterprise SSO or WorkOS connector.",
        "Effort": "High (2-3 days)",
        "Priority": "P3 (Roadmap)"
    },
    {
        "Issue ID": "SEC-010",
        "Category": "Secret & Credential Management",
        "Severity": "Low",
        "Vulnerability Title": "Static Fallback Secret Key in Code",
        "Description": "JWT_SECRET defaults to fallback string 'your-secret-key-change-in-production' if environment variable is unset.",
        "Impact / Risk": "If deployed without .env, all tokens could be forged using the known default secret.",
        "File & Line Location": "GEO-backend/app.py (Line 61)",
        "Recommended Fix": "Raise a fatal configuration error on startup if JWT_SECRET or SUPABASE_KEY is missing rather than falling back to a default.",
        "Effort": "Low (15 mins)",
        "Priority": "P1 (High)"
    }
]

# Define Policies & Governance Dataset
governance_data = [
    {
        "Section": "1. Data Handling & Isolation",
        "Policy Requirement": "Tenant Isolation",
        "Current Implementation Status": "Implemented (by user_id & project_id)",
        "Audit Recommendation": "Ensure every database query includes user_id filter."
    },
    {
        "Section": "1. Data Handling & Isolation",
        "Policy Requirement": "Zero AI Model Training Guarantee",
        "Current Implementation Status": "Compliant (via Enterprise API terms)",
        "Audit Recommendation": "State explicitly in Client DPA that data is not used to train AI models."
    },
    {
        "Section": "2. Encryption Standards",
        "Policy Requirement": "Encryption in Transit",
        "Current Implementation Status": "TLS 1.2 / 1.3 on production domains",
        "Audit Recommendation": "Enforce Strict-Transport-Security (HSTS) headers."
    },
    {
        "Section": "2. Encryption Standards",
        "Policy Requirement": "Encryption at Rest",
        "Current Implementation Status": "AES-256 via Supabase storage engine",
        "Audit Recommendation": "Document automated key rotation with cloud provider."
    },
    {
        "Section": "3. Data Retention & Erasure",
        "Policy Requirement": "Data Retention Policy",
        "Current Implementation Status": "Indefinite for projects; temporary logs 30 days",
        "Audit Recommendation": "Add automated cron to purge orphaned scraped sessions > 90 days."
    },
    {
        "Section": "3. Data Retention & Erasure",
        "Policy Requirement": "Account Deletion (Right to be Forgotten)",
        "Current Implementation Status": "Partial (Project deletion exists; user-level manual)",
        "Audit Recommendation": "Expose full self-service account deletion in account settings."
    },
    {
        "Section": "4. Incident Management",
        "Policy Requirement": "Incident Response SLA",
        "Current Implementation Status": "Documented: 1hr ack, 24hr breach notice",
        "Audit Recommendation": "Establish designated security@optimiseurbrand.tech mailbox."
    }
]

# Create DataFrames
df_issues = pd.DataFrame(issues_data)
df_gov = pd.DataFrame(governance_data)

file_path = "d:/GEO-POD1/GEO_Security_and_Privacy_Audit_Report.xlsx"

with pd.ExcelWriter(file_path, engine="openpyxl") as writer:
    df_issues.to_excel(writer, sheet_name="Security & Privacy Issues", index=False)
    df_gov.to_excel(writer, sheet_name="Compliance & Governance Plan", index=False)

# Format Excel Workbook with professional enterprise styling
wb = openpyxl.load_workbook(file_path)

# Header formatting style
header_fill = PatternFill(start_color="1E293B", end_color="1E293B", fill_type="solid") # Dark Slate
header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
thin_border = Border(
    left=Side(style="thin", color="CBD5E1"),
    right=Side(style="thin", color="CBD5E1"),
    top=Side(style="thin", color="CBD5E1"),
    bottom=Side(style="thin", color="CBD5E1")
)

# Severity color fills
sev_fills = {
    "Critical": PatternFill(start_color="FEE2E2", end_color="FEE2E2", fill_type="solid"), # Light Red
    "High": PatternFill(start_color="FFEDD5", end_color="FFEDD5", fill_type="solid"),     # Light Orange
    "Medium": PatternFill(start_color="FEF3C7", end_color="FEF3C7", fill_type="solid"),   # Light Yellow
    "Low": PatternFill(start_color="E0F2FE", end_color="E0F2FE", fill_type="solid")       # Light Blue
}
sev_fonts = {
    "Critical": Font(name="Calibri", size=10, bold=True, color="991B1B"),
    "High": Font(name="Calibri", size=10, bold=True, color="9A3412"),
    "Medium": Font(name="Calibri", size=10, bold=True, color="854D0E"),
    "Low": Font(name="Calibri", size=10, bold=True, color="075985")
}

for sheetname in wb.sheetnames:
    ws = wb[sheetname]
    ws.views.sheetView[0].showGridLines = True
    
    # Format Headers
    for col_idx in range(1, ws.max_column + 1):
        cell = ws.cell(row=1, column=col_idx)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        ws.row_dimensions[1].height = 28

    # Format Data Rows
    for row_idx in range(2, ws.max_row + 1):
        ws.row_dimensions[row_idx].height = 55
        for col_idx in range(1, ws.max_column + 1):
            cell = ws.cell(row=row_idx, column=col_idx)
            cell.border = thin_border
            cell.font = Font(name="Calibri", size=10)
            cell.alignment = Alignment(vertical="center", wrap_text=True)
            
            # Severity column styling in Sheet 1
            if sheetname == "Security & Privacy Issues" and col_idx == 3:
                sev = cell.value
                if sev in sev_fills:
                    cell.fill = sev_fills[sev]
                    cell.font = sev_fonts[sev]
                    cell.alignment = Alignment(horizontal="center", vertical="center")

    # Adjust Column Widths
    for col in ws.columns:
        max_len = max(len(str(cell.value or '')) for cell in col)
        col_letter = get_column_letter(col[0].column)
        ws.column_dimensions[col_letter].width = min(max(max_len + 4, 14), 45)

wb.save(file_path)
print(f"Successfully generated Excel report at {file_path}")
