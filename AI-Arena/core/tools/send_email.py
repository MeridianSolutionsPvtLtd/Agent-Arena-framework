import os
import logging
import re
import json
import time
from azure.communication.email import EmailClient
from crewai.tools import BaseTool
from typing import Type
from core.security.guardrails import GuardrailEngine

logger = logging.getLogger(__name__)


def _resolve_email_placeholder(value: str) -> str:
    text = (value or "").strip()
    if not re.fullmatch(r"<PII_EMAIL_\d+>", text):
        return text
    try:
        raw = os.getenv("AGENT_PII_MAP_JSON", "")
        mapping = json.loads(raw) if raw else {}
        resolved = (mapping or {}).get(text, "")
        return resolved or text
    except Exception:
        return text

def markdown_to_html_table(markdown_text: str) -> str:
    """Converts standard Markdown tables into styled HTML tables for emails."""
    lines = [line.strip() for line in markdown_text.split('\n') if line.strip()]
    if not lines or '|' not in lines[0]:
        return markdown_text

    html_table = '<table style="width:100%; border-collapse:collapse; margin:20px 0; font-family: sans-serif; font-size: 14px; color: #333; background: #fff; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1); border-radius: 8px; overflow: hidden;">'
    
    header_processed = False
    for line in lines:
        if '---' in line and '|' in line: # Skip separator row
            continue
        
        cells = [c.strip() for c in line.split('|') if c.strip()]
        if not cells: continue

        if not header_processed:
            html_table += '<tr style="background-color: #1e293b; color: #ffffff; text-align: left; font-weight: bold;">'
            for cell in cells:
                html_table += f'<th style="padding: 12px 15px; border: 1px solid #e2e8f0;">{cell}</th>'
            html_table += '</tr>'
            header_processed = True
        else:
            html_table += '<tr style="border-bottom: 1px solid #f1f5f9;">'
            for cell in cells:
                html_table += f'<td style="padding: 12px 15px; border: 1px solid #e2e8f0;">{cell}</td>'
            html_table += '</tr>'
    
    html_table += '</table>'
    return html_table

from pydantic import BaseModel, Field

class EmailInput(BaseModel):
    recipient: str = Field(..., description="The email address of the recipient. Can be a real email or a <PII_EMAIL_n> token.")
    subject: str = Field(..., description="The subject line of the email.")
    body: str = Field(..., description="The main content of the email. Supports Markdown (tables, code blocks) which will be styled automatically.")

class EmailTool(BaseTool):
    name: str = "send_email"
    description: str = """
    Sends a premium branded HTML email report.
    
    USE THIS TOOL WHEN:
    - You need to send a final report, summary, or notification to a user via email.
    - The task specifically requests 'emailing' or 'mailing' results.
    
    INPUT:
    - recipient: A valid email or PII placeholder.
    - subject: Professional subject line.
    - body: Detailed content. Markdown tables are automatically converted to beautiful HTML tables.
    
    DO NOT:
    - Send emails without a clear request from the user.
    - Leave the subject or body empty.
    
    Example:
    {"recipient": "user@example.com", "subject": "Quarterly Report", "body": "### Data Summary\n| Q1 | Q2 |\n|---|---|\n| 10 | 20 |"}
    """
    args_schema: Type[BaseModel] = EmailInput

    def _run(self, recipient: str, subject: str, body: str) -> str:
        """Internal execution logic."""
        connection_string = os.getenv("AZURE_COMMUNICATION_CONNECTION_STRING")
        sender_address = os.getenv("AZURE_SENDER_ADDRESS")
        recipient = GuardrailEngine.resolve_runtime_pii(recipient or "")
        recipient = _resolve_email_placeholder(recipient)
        subject = GuardrailEngine.resolve_runtime_pii(subject or "")
        body = GuardrailEngine.resolve_runtime_pii(body or "")
    
        if not connection_string or connection_string == "your_connection_string_here":
            return "Skipped: Azure Email connection string not set."
        if not sender_address:
            return "Failed to send email: AZURE_SENDER_ADDRESS is not configured."
    
        # 1. Convert Markdown to HTML using a robust library
        import markdown
        # We use 'tables' and 'fenced_code' extensions for full feature support
        processed_body = markdown.markdown(body, extensions=['tables', 'fenced_code', 'nl2br'])
    
        # Wrap in Premium HTML Template
        html_content = f"""
        <html>
        <head>
        <style>
            body {{ font-family: 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; line-height: 1.6; color: #334155; }}
            h1, h2, h3 {{ color: #0f172a; margin-top: 1.5em; margin-bottom: 0.5em; font-weight: 800; }}
            p {{ margin-bottom: 1.2em; }}
            table {{ width: 100%; border-collapse: collapse; margin: 25px 0; font-size: 14px; background: #fff; border-radius: 8px; overflow: hidden; border: 1px solid #e2e8f0; }}
            th {{ background-color: #f8fafc; color: #64748b; text-align: left; font-weight: 700; padding: 12px 15px; border-bottom: 2px solid #e2e8f0; text-transform: uppercase; letter-spacing: 1px; font-size: 11px; }}
            td {{ padding: 12px 15px; border-bottom: 1px solid #f1f5f9; }}
            tr:last-child td {{ border-bottom: none; }}
            pre {{
                background-color: #0f172a;
                color: #e2e8f0;
                padding: 20px;
                border-radius: 12px;
                font-family: 'Consolas', monospace;
                font-size: 13px;
                overflow-x: auto;
                margin: 25px 0;
            }}
            code {{ background-color: #f1f5f9; padding: 2px 4px; border-radius: 4px; font-family: monospace; color: #ef4444; }}
            pre code {{ background-color: transparent; padding: 0; color: inherit; }}
            blockquote {{
                border-left: 4px solid #3b82f6;
                margin: 25px 0;
                padding: 15px 25px;
                background-color: #f8fafc;
                color: #475569;
                font-style: italic;
            }}
            ul, ol {{ padding-left: 25px; margin-bottom: 1.5em; }}
            li {{ margin-bottom: 0.5em; }}
        </style>
        </head>
        <body style="margin: 0; padding: 0; background-color: #f8fafc;">
            <div style="max-width: 850px; margin: 40px auto; background: #ffffff; border-radius: 20px; overflow: hidden; box-shadow: 0 20px 25px -5px rgba(0,0,0,0.05); border: 1px solid #e2e8f0;">
                <div style="background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%); padding: 50px 40px; text-align: center;">
                    <h1 style="color: #ffffff; margin: 0; font-size: 32px; letter-spacing: 4px; font-weight: 900; text-transform: uppercase;">AGENT ARENA</h1>
                    <p style="color: #60a5fa; margin: 12px 0 0 0; font-size: 13px; text-transform: uppercase; letter-spacing: 4px; font-weight: 700;">Intelligence Synthesis Report</p>
                </div>
                <div style="padding: 60px 50px;">
                    <div style="margin-bottom: 40px; border-bottom: 2px solid #f1f5f9; padding-bottom: 20px;">
                        <h2 style="margin: 0; color: #0f172a; font-size: 24px; tracking: -0.02em;">{subject}</h2>
                    </div>
                    <div class="content-body">
                        {processed_body}
                    </div>
                </div>
                <div style="background: #f8fafc; padding: 40px; text-align: center; color: #94a3b8; font-size: 11px; border-top: 1px solid #f1f5f9;">
                    <p style="margin: 0; font-weight: 700; color: #64748b; letter-spacing: 1px; text-transform: uppercase;">AUTONOMOUS AGENTIC COMMUNICATION</p>
                    <p style="margin: 10px 0 0 0;">Meridian Solutions &copy; 2026. This report was synthesized and delivered by an autonomous workforce.</p>
                </div>
            </div>
        </body>
        </html>
        """

        client = EmailClient.from_connection_string(connection_string)
        
        email_addresses = []
        for r in recipient.split(","):
            r = r.strip()
            if r:
                email_addresses.append(r)
                
        if not email_addresses:
            return "No valid recipients found."
            
        success_count = 0
        error_logs = []
        
        for email_addr in email_addresses:
            message = {
                "content": {
                    "subject": subject,
                    "plainText": body,
                    "html": html_content
                },
                "recipients": {
                    "to": [{"address": email_addr}]
                },
                "senderAddress": sender_address
            }
        
            max_attempts = 3
            last_error = ""
            for attempt in range(1, max_attempts + 1):
                try:
                    poller = client.begin_send(message)
                    _ = poller.result()
                    success_count += 1
                    break
                except Exception as e:
                    last_error = str(e)
                    logger.error(f"Failed to send to {email_addr} (attempt {attempt}): {last_error}")
                    transient = any(tok in last_error.lower() for tok in [
                        "connection aborted", "remote end closed connection", 
                        "temporarily unavailable", "timeout", "timed out", "connection reset"
                    ])
                    if not transient or attempt >= max_attempts:
                        error_logs.append(f"{email_addr}: {last_error}")
                        break
                    time.sleep(1.5 * attempt)
        
        if success_count == len(email_addresses):
            addr_str = ", ".join(email_addresses)
            # Include explicit addresses so downstream final-answer synthesis cannot invent recipients.
            return (
                f"Premium Report successfully sent to {success_count} recipient(s). "
                f"Recipients (verbatim): {addr_str}"
            )
        else:
            return f"Sent to {success_count}/{len(email_addresses)}. Errors: {'; '.join(error_logs)}"
