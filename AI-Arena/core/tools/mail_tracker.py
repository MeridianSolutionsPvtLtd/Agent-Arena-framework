import base64
import json
import logging
import os
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Type
 
from crewai.tools import BaseTool
from pydantic import BaseModel, Field
import msal
 
logger = logging.getLogger(__name__)
 
 
class MailboxTrackerGraphInput(BaseModel):
    """Input schema for mailbox_tracker_graph."""
 
    action: str = Field(
        default="fetch_new",
        description="Action: 'fetch_new', 'search', or 'mark_read'.",
    )
    subject_contains: str = Field(
        default="",
        description="Optional subject keyword filter.",
    )
    sender_domain: str = Field(
        default="",
        description="Optional sender domain filter (example: contoso.com).",
    )
    max_results: int = Field(default=10, description="Max emails to return (1-50).")
    include_attachments: bool = Field(
        default=True,
        description="If true, attachment metadata is returned and files are downloaded.",
    )
    attachment_dir: str = Field(
        default="mail_attachments_graph",
        description="Directory path for downloaded attachments.",
    )
    mark_as_read: bool = Field(
        default=False,
        description="When true, emails returned by fetch/search are marked read.",
    )
    message_id: str = Field(
        default="",
        description="Required for action='mark_read'.",
    )
    access_token: str = Field(
        default="",
        description="Optional OAuth access token; if empty, GRAPH_ACCESS_TOKEN env is used.",
    )
    target_user: str = Field(
        default="me",
        description="Use 'me' for delegated token, or mailbox user id/email for app-token access.",
    )
 
 
class MailboxTrackerGraphTool(BaseTool):
    name: str = "mailbox_tracker_graph"
    description: str = (
        "Mailbox tracking and management via Microsoft Graph API. "
        "Allows you to list, search, and manage emails and attachments. "
        "\n\nUSE THIS TOOL WHEN:"
        "\n- You need to check for new/unread emails (action='fetch_new')."
        "\n- You need to search for specific emails by subject or domain (action='search')."
        "\n- You need to download email attachments (handled automatically in fetch/search)."
        "\n- You need to mark an email as read (action='mark_read' + message_id)."
        "\n\nINPUT ACTIONS:"
        "\n1. 'fetch_new': Returns recent unread emails."
        "\n2. 'search': Use with 'subject_contains' or 'sender_domain'."
        "\n3. 'mark_read': Requires the exact 'message_id' returned from a previous fetch/search."
        "\n\nRULES:"
        "\n- Always check the 'emails' list in the JSON output."
        "\n- Attachments are downloaded to 'mail_attachments_graph/' by default."
    )
    args_schema: Type[BaseModel] = MailboxTrackerGraphInput
 
    def _get_graph_token(self, explicit_token: str = "") -> str:
        # Highest priority: direct token passed in tool input.
        if explicit_token.strip():
            return explicit_token.strip()
 
        # Fallback: static env token (legacy/manual mode).
        env_token = os.getenv("GRAPH_ACCESS_TOKEN", "").strip()
        if env_token:
            return env_token
 
        # Preferred: MSAL confidential-client auto token acquisition.
        tenant_id = os.getenv("GRAPH_TENANT_ID", "").strip()
        client_id = os.getenv("GRAPH_CLIENT_ID", "").strip()
        client_secret = os.getenv("GRAPH_CLIENT_SECRET", "").strip()
        authority = os.getenv("GRAPH_AUTHORITY", "").strip() or (
            f"https://login.microsoftonline.com/{tenant_id}" if tenant_id else ""
        )
        scope_value = os.getenv("GRAPH_SCOPE", "https://graph.microsoft.com/.default").strip()
        scopes = [s.strip() for s in scope_value.split(",") if s.strip()]
 
        if not authority or not client_id or not client_secret:
            return ""
 
        app = msal.ConfidentialClientApplication(
            client_id=client_id,
            authority=authority,
            client_credential=client_secret,
        )
        token_result = app.acquire_token_for_client(scopes=scopes)
        return token_result.get("access_token", "")
 
    def _graph_base(self, target_user: str) -> str:
        user = (target_user or "me").strip()
        if user.lower() == "me":
            return "https://graph.microsoft.com/v1.0/me"
        return f"https://graph.microsoft.com/v1.0/users/{urllib.parse.quote(user)}"
 
    def _request_json(
        self,
        url: str,
        token: str,
        method: str = "GET",
        body: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
 
        req = urllib.request.Request(
            url=url,
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=20) as response:
            raw = response.read().decode("utf-8", errors="ignore")
            return json.loads(raw) if raw else {}
 
    def _download_attachments(
        self,
        token: str,
        base: str,
        message_id: str,
        attachment_dir: str,
    ) -> List[Dict[str, str]]:
        safe_dir = Path(attachment_dir)
        safe_dir.mkdir(parents=True, exist_ok=True)
 
        url = f"{base}/messages/{urllib.parse.quote(message_id)}/attachments?$top=30"
        payload = self._request_json(url, token)
        items = payload.get("value", [])
 
        saved_files: List[Dict[str, str]] = []
        for item in items:
            if item.get("@odata.type", "").endswith("fileAttachment"):
                file_name = item.get("name") or "attachment.bin"
                content_bytes = item.get("contentBytes")
                if not content_bytes:
                    continue
 
                data = base64.b64decode(content_bytes)
                target = safe_dir / file_name
                idx = 1
                while target.exists():
                    target = safe_dir / f"{target.stem}_{idx}{target.suffix}"
                    idx += 1
 
                with open(target, "wb") as f:
                    f.write(data)
 
                saved_files.append(
                    {
                        "filename": target.name,
                        "path": str(target.resolve()),
                        "size_bytes": str(len(data)),
                    }
                )
        return saved_files
 
    def _build_filter(self, action: str, subject_contains: str, sender_domain: str) -> str:
        parts: List[str] = []
        if action == "fetch_new":
            parts.append("isRead eq false")
        if subject_contains:
            escaped = subject_contains.replace("'", "''")
            parts.append(f"contains(subject,'{escaped}')")
        if sender_domain:
            domain = sender_domain.lower().replace("@", "").replace("'", "''")
            parts.append(f"endswith(from/emailAddress/address,'@{domain}')")
        return " and ".join(parts)
 
    def _mark_read(self, token: str, base: str, message_id: str) -> Dict[str, Any]:
        patch_url = f"{base}/messages/{urllib.parse.quote(message_id)}"
        self._request_json(patch_url, token, method="PATCH", body={"isRead": True})
        return {"message_id": message_id, "status": "marked_read"}
 
    def _run(
        self,
        action: str = "fetch_new",
        subject_contains: str = "",
        sender_domain: str = "",
        max_results: int = 10,
        include_attachments: bool = True,
        attachment_dir: str = "mail_attachments_graph",
        mark_as_read: bool = False,
        message_id: str = "",
        access_token: str = "",
        target_user: str = "me",
    ) -> str:
        token = self._get_graph_token(access_token)
        if not token:
            return json.dumps(
                {
                    "error": (
                        "Missing Graph auth. Provide access_token OR configure MSAL env vars: "
                        "GRAPH_TENANT_ID, GRAPH_CLIENT_ID, GRAPH_CLIENT_SECRET "
                        "(optional GRAPH_SCOPE, GRAPH_AUTHORITY)."
                    )
                }
            )
 
        base = self._graph_base(target_user)
        safe_max = max(1, min(max_results, 50))
        normalized_action = (action or "fetch_new").lower().strip()
 
        try:
            if normalized_action == "mark_read":
                if not message_id:
                    return json.dumps({"error": "message_id is required for action='mark_read'."})
                result = self._mark_read(token, base, message_id)
                return json.dumps(result, indent=2)
 
            if normalized_action not in {"fetch_new", "search"}:
                return json.dumps({"error": "Invalid action. Use 'fetch_new', 'search', or 'mark_read'."})
 
            filter_expr = self._build_filter(normalized_action, subject_contains, sender_domain)
            params = {
                "$top": str(safe_max),
                "$orderby": "receivedDateTime desc",
                "$select": "id,subject,from,receivedDateTime,isRead,bodyPreview,hasAttachments",
            }
            if filter_expr:
                params["$filter"] = filter_expr
 
            qs = urllib.parse.urlencode(params, safe="(),'@/ ")
            list_url = f"{base}/mailFolders/inbox/messages?{qs}"
            payload = self._request_json(list_url, token)
            emails = payload.get("value", [])
 
            results: List[Dict[str, Any]] = []
            for mail in emails:
                item = {
                    "id": mail.get("id", ""),
                    "subject": mail.get("subject", ""),
                    "from": (((mail.get("from") or {}).get("emailAddress") or {}).get("address") or "").lower(),
                    "receivedDateTime": mail.get("receivedDateTime", ""),
                    "isRead": bool(mail.get("isRead", False)),
                    "bodyPreview": mail.get("bodyPreview", ""),
                    "hasAttachments": bool(mail.get("hasAttachments", False)),
                    "tracked_at": datetime.utcnow().isoformat() + "Z",
                    "attachments": [],
                }
 
                if include_attachments and item["hasAttachments"] and item["id"]:
                    item["attachments"] = self._download_attachments(
                        token=token,
                        base=base,
                        message_id=item["id"],
                        attachment_dir=attachment_dir,
                    )
 
                if mark_as_read and item["id"]:
                    self._mark_read(token, base, item["id"])
                    item["isRead"] = True
 
                results.append(item)
 
            return json.dumps(
                {
                    "action": normalized_action,
                    "target_user": target_user,
                    "total_found": len(results),
                    "filters": {
                        "subject_contains": subject_contains,
                        "sender_domain": sender_domain,
                    },
                    "emails": results,
                },
                indent=2,
            )
        except Exception as e:
            logger.exception("mailbox_tracker_graph failed")
            return json.dumps({"error": str(e)})
 
 
mailbox_tracker_graph = MailboxTrackerGraphTool()
 
 