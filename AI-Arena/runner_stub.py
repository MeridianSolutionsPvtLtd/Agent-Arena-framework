import os
import re
import sys
import shutil
import uuid

# Package root = folder that contains `core/` and `agent.json`
_ROOT = os.path.dirname(os.path.abspath(__file__))
if getattr(sys, "frozen", False):
    _ROOT = getattr(sys, "_MEIPASS", _ROOT)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import json
from dotenv import load_dotenv

from core.orchestration.executor import AgentExecutor
from core.tools.init_tools import register_default_tools

UPLOADS_DIR = os.path.join(_ROOT, "uploads")
_WIN_PATH_RE = re.compile(r"(?:[A-Za-z]:\\|\\\\)[^\s\"']+")
_APPROVAL_WORDS = frozenset(
    {"yes", "approved", "ok", "go ahead", "approve", "yep", "sure", "do it", "proceed", "continue", "yes continue"}
)


def _ensure_uploads_dir() -> None:
    os.makedirs(UPLOADS_DIR, exist_ok=True)


def _copy_into_uploads(source: str) -> str:
    """Copy a user file into ./uploads and return absolute path."""
    source = os.path.abspath(os.path.expanduser(source.strip().strip('"')))
    if not os.path.isfile(source):
        raise FileNotFoundError(f"File not found: {source}")
    _ensure_uploads_dir()
    base = os.path.basename(source)
    safe = re.sub(r"[^\w.\- ]", "_", base)[:180] or "upload"
    dest = os.path.join(UPLOADS_DIR, f"{uuid.uuid4().hex[:10]}_{safe}")
    shutil.copy2(source, dest)
    return os.path.abspath(dest)


def _extract_paths_from_text(text: str) -> list[str]:
    found = []
    for m in _WIN_PATH_RE.findall(text or ""):
        p = m.strip().rstrip(".,);]")
        if os.path.isfile(p):
            found.append(os.path.abspath(p))
    return found


def _append_file_paths_to_query(query: str, file_paths: list[str]) -> str:
    if not file_paths:
        return query
    suffix = " ".join(f"(local path: {p})" for p in file_paths)
    return f"{query} {suffix}".strip()


def _print_help() -> None:
    print(
        "\nCommands:\n"
        "  attach <file path>   Add a file (PDF, Excel, CSV, image, etc.)\n"
        "  files                List attached files\n"
        "  clear files          Remove all attachments\n"
        "  help                 Show this help\n"
        "  exit / quit          Exit\n"
        "\nTips:\n"
        "  - You can paste a full path in your message: C:\\Docs\\report.pdf\n"
        "  - After a flight plan appears, type yes / approved to run it.\n"
    )


def _handle_attach_command(parts: list[str], attached: list[str]) -> None:
    if len(parts) < 2:
        print("Usage: attach C:\\path\\to\\your\\file.pdf")
        return
    raw = " ".join(parts[1:]).strip().strip('"')
    try:
        dest = _copy_into_uploads(raw)
        if dest not in attached:
            attached.append(dest)
        print(f"Attached: {dest}")
    except Exception as e:
        print(f"Could not attach file: {e}")


def _run_turn(
    blueprint: dict,
    user_text: str,
    attached_files: list[str],
    conversation_history: str,
    pre_approved_plan: list,
    blackboard: dict,
) -> dict:
    extra_paths = _extract_paths_from_text(user_text)
    all_paths = list(dict.fromkeys(attached_files + extra_paths))
    query = _append_file_paths_to_query(user_text, all_paths)

    return AgentExecutor.run(
        blueprint=blueprint,
        query=query,
        conversation_history=conversation_history,
        file_paths=all_paths,
        pre_approved_plan=pre_approved_plan,
        blackboard=blackboard,
    )


def main():
    print("====================================")
    print(" Agent Arena - Portable Base Runner ")
    print("====================================")

    base_path = _ROOT
    config_path = os.path.join(base_path, "agent.json")

    if not os.path.isdir(os.path.join(base_path, "core")):
        print("Error: 'core' package folder is missing next to runner_stub.py.")
        print("Re-download the portable ZIP from Agent Arena (full package).")
        input("Press Enter to exit...")
        sys.exit(1)

    if not os.path.exists(config_path):
        print(f"Error: agent.json not found at {config_path}")
        input("Press Enter to exit...")
        sys.exit(1)

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            blueprint = json.load(f)
    except Exception as e:
        print(f"Failed to load agent.json: {e}")
        sys.exit(1)

    print(f"Loaded Agent Blueprint: {blueprint.get('name', 'Unknown Agent')}")
    print(f"Domain: {blueprint.get('domain', 'Unknown Domain')}")
    _ensure_uploads_dir()
    print(f"Upload folder: {UPLOADS_DIR}")
    print("Type 'help' for commands (attach files, approve plans).")
    print("------------------------------------\n")

    load_dotenv(os.path.join(base_path, ".env"))

    os.environ["LLM_PROVIDER"] = "ollama"
    print(f"Local Ollama model: {os.getenv('OLLAMA_MODEL', 'llama3.1')}")

    register_default_tools()

    attached_files: list[str] = []
    conversation_history = ""
    pre_approved_plan: list = []
    blackboard: dict = {}
    pending_plan_display: str = ""

    while True:
        try:
            user_text = input("\n[You]: ").strip()
            if not user_text:
                continue

            low = user_text.lower()
            if low in ("exit", "quit"):
                break
            if low == "help":
                _print_help()
                continue
            if low == "files":
                if attached_files:
                    for i, p in enumerate(attached_files, 1):
                        print(f"  {i}. {p}")
                else:
                    print("No files attached. Use: attach C:\\path\\to\\file.pdf")
                continue
            if low in ("clear files", "clear"):
                attached_files.clear()
                print("Cleared attached files.")
                continue
            if low.startswith("attach ") or low.startswith("upload "):
                _handle_attach_command(user_text.split(), attached_files)
                continue

            agent_name = blueprint.get("name", "Agent")
            print(f"\n[{agent_name} is analyzing...]")

            use_plan = []
            if low in _APPROVAL_WORDS and pre_approved_plan:
                use_plan = pre_approved_plan
            elif low in _APPROVAL_WORDS and pending_plan_display:
                print("No structured plan in memory. Re-ask your task or wait for a new flight plan.")
                continue

            result = _run_turn(
                blueprint=blueprint,
                user_text=user_text,
                attached_files=attached_files,
                conversation_history=conversation_history,
                pre_approved_plan=use_plan,
                blackboard=blackboard,
            )

            msg = result.get("message", "")
            if result.get("hitl_pending"):
                pending_plan_display = msg
                pre_approved_plan = result.get("structured_plan") or []
                print(f"\n[{agent_name}]:\n{msg}")
                print("\n>>> Type yes / approved to run this plan, or ask for changes.")
            else:
                pending_plan_display = ""
                pre_approved_plan = []
                print(f"\n[{agent_name}]: {msg}")

            if result.get("blackboard"):
                blackboard = result["blackboard"]

            conversation_history += f"\nUser: {user_text}\nAgent: {msg[:4000]}"

        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"\n[System Error]: {e}")

    print("Agent shut down successfully.")


if __name__ == "__main__":
    main()
