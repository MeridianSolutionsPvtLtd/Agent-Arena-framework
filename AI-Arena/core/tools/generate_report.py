import os
import json
import logging
from datetime import datetime
from typing import Type, Optional
from pydantic import BaseModel, Field
from crewai.tools import BaseTool
from core.orchestration.azure_settings import model_completion

logger = logging.getLogger(__name__)


# ---------------- INPUT SCHEMA ----------------
class ReportGeneratorInput(BaseModel):
    content: str = Field(..., description="Raw content or research data")
    title: str = Field(..., description="Report title")
    format: str = Field("markdown", description="'markdown', 'pdf', or 'both'")
    persona: Optional[dict] = Field(None, description="Sub-agent persona (role, backstory, goal)")


# ---------------- TOOL ----------------
class ReportGeneratorTool(BaseTool):
    name: str = "generate_report"
    description: str = "Generate structured business reports with optional PDF export"
    args_schema: Type[BaseModel] = ReportGeneratorInput

    def _run(self, content: str, title: str, format: str = "markdown", persona: Optional[dict] = None) -> str:
        try:
            logger.info(f"[ReportGenerator] Starting | Title: {title} | Format: {format}")

            # 🔒 Normalize format
            format = (format or "markdown").lower()
            if format not in ["markdown", "pdf", "both"]:
                format = "markdown"

            # 🔒 Trim content (prevent token overflow)
            content = content[:20000]

            # 1. LLM Structuring
            report_md = self._professionalize_with_llm(content, title, persona=persona)

            # 2. Output directory
            output_dir = os.path.join(os.getcwd(), "outputs")
            os.makedirs(output_dir, exist_ok=True)

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_title = self._sanitize_filename(title)

            files_generated = []

            # 3. Save Markdown
            if format in ["markdown", "both"]:
                md_path = os.path.join(output_dir, f"Report_{safe_title}_{timestamp}.md")
                with open(md_path, "w", encoding="utf-8") as f:
                    f.write(report_md)

                files_generated.append(md_path)

            # 4. Save PDF
            if format in ["pdf", "both"]:
                pdf_path = self._generate_pdf(report_md, title, safe_title, timestamp, output_dir)

                if pdf_path:
                    files_generated.append(pdf_path)

            logger.info(f"[ReportGenerator] Files generated: {files_generated}")

            return json.dumps({
                "status": "success",
                "files": files_generated,
                "preview": report_md[:800] + ("..." if len(report_md) > 800 else "")
            }, indent=2)

        except Exception as e:
            logger.error(f"[ReportGenerator] Failed: {e}")
            return json.dumps({"status": "error", "message": str(e)})


    # ---------------- LLM STRUCTURING ----------------
    def _professionalize_with_llm(self, content: str, title: str, persona: Optional[dict] = None) -> str:
        persona = persona or {}
        agent_role = persona.get("role") or "professional business analyst"
        backstory = persona.get("backstory") or ""
        goal = persona.get("goal") or ""

        prompt = f"""
You are a {agent_role}.
{"BACKSTORY: " + backstory if backstory else ""}
{"GOAL: " + goal if goal else ""}

Create a structured report.

TITLE: {title}

CONTENT:
{content}

---

FORMAT:
By default, use this structure:
# Title
## Executive Summary
## Key Findings
## Analysis
## Recommendations
## Conclusion

*ADAPTABILITY:* If the TITLE or CONTENT clearly implies a different format (e.g., a "Job Description", "Email Draft", or "Resume"), completely IGNORE the default report structure above and output the appropriate professional format for that specific document.

Keep it concise, structured, and professional.

STRICT GUIDELINES:
1. NO PLACEHOLDERS OR BOILERPLATE: NEVER use text like "[Insert Name]", "[insert contact details]", "[Your Email]", "[insert application email or link]", or ANY bracketed placeholders. Do NOT invent generic sections (e.g., "Contact Us", "Why Join Us", "How to Apply") if the specific details are not provided in the CONTENT. If a detail is missing, simply omit that sentence or section entirely.
2. DATA GROUNDING: If the CONTENT mentions a date or spec, you MUST use it in the corresponding sections.
3. COMPLETENESS: Ensure the Technical Specifications and Deadlines are clearly extracted from the CONTENT.
4. URLs / LINKS: Only cite https URLs that appear verbatim in the CONTENT (e.g. from web_search JSON "url" fields). NEVER invent or guess canonical links for Khan Academy, Wikipedia, publisher sites, or YouTube — fabricated URLs look plausible but are wrong.
5. CRITICAL EVALUATION RULE: If your task is to evaluate, rank, score, or analyze candidates/vendors against a Job Description or requirements found in the CONTENT, you MUST anchor your analysis STRICTLY to those provided criteria. Do NOT reward irrelevant skills (e.g., AI/ML if the JD is for Frontend) or penalize for lacking unrequested skills.
"""

        try:
            res = model_completion(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=2500,
            )

            return res.choices[0].message.content.strip()

        except Exception as e:
            logger.warning(f"[LLM FAILED] Using fallback: {e}")
            return f"# {title}\n\n{content}"


    # ---------------- PDF GENERATION ----------------
    def _generate_pdf(self, md_content: str, title: str, safe_title: str, timestamp: str, output_dir: str) -> Optional[str]:
        try:
            from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
            from reportlab.lib.styles import getSampleStyleSheet
            from reportlab.lib.pagesizes import A4
            import re
            import html

            pdf_path = os.path.join(output_dir, f"Report_{safe_title}_{timestamp}.pdf")
            doc = SimpleDocTemplate(pdf_path, pagesize=A4)
            styles = getSampleStyleSheet()

            elements = []

            def md_to_pdf_tags(text):
                # Escape HTML first
                text = html.escape(text)

                # Bold FIRST
                text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', text)

                # Italic (avoid matching bold)
                text = re.sub(r'(?<!\*)\*(?!\*)(.*?)\*(?<!\*)', r'<i>\1</i>', text)

                return text

            for line in md_content.split("\n"):
                line = line.strip()

                if not line:
                    elements.append(Spacer(1, 10))
                    continue

                # Prevent overflow
                if len(line) > 1000:
                    line = line[:1000] + "..."

                if line.startswith("# "):
                    elements.append(Paragraph(md_to_pdf_tags(line[2:]), styles["Heading1"]))
                elif line.startswith("## "):
                    elements.append(Paragraph(md_to_pdf_tags(line[3:]), styles["Heading2"]))
                elif line.startswith("### "):
                    elements.append(Paragraph(md_to_pdf_tags(line[4:]), styles["Heading3"]))
                elif line.startswith("- ") or line.startswith("* "):
                    elements.append(Paragraph(f"&bull; {md_to_pdf_tags(line[2:])}", styles["Normal"]))
                else:
                    elements.append(Paragraph(md_to_pdf_tags(line), styles["Normal"]))

                elements.append(Spacer(1, 6))

            doc.build(elements)

            return pdf_path

        except Exception as e:
            logger.error(f"[PDF ERROR] {e}")
            return f"[PDF_GENERATION_FAILED]: {str(e)}"


    # ---------------- UTIL ----------------
    def _sanitize_filename(self, title: str) -> str:
        return "".join(c if c.isalnum() else "_" for c in title).strip("_")
