# Downloadable Agent `.exe` Setup

This document explains how the downloadable agent system works in this codebase, how to set it up, and what files were added or changed.

## Goal

Users should be able to create an agent in Agent Arena, click **Download Agent**, download a Windows `.exe`, run it on their system, log in, and start using that agent.

The `.exe` is intentionally a **thin client**. It does **not** contain your full framework code, tools, prompts, Mongo credentials, or LLM keys. It only contains:

- `agent_id`
- `agent_name`
- backend API URL

The actual agent execution still happens on your FastAPI backend.

## Architecture

```text
Downloaded Agent.exe
  - opens the same React chat UI inside a Tauri desktop window
  - asks user to log in
  - supports chat
  - supports file attach/upload
  - calls FastAPI backend

FastAPI Backend
  - owns agent blueprint
  - owns orchestration/core code
  - owns tools
  - owns Azure/OpenAI keys
  - owns MongoDB memory
  - runs /agents/{agent_id}/run
```

This protects your code better than ZIP because the customer does not receive the `core/` framework folder.

## User Flow

1. User creates an agent in the web app.
2. User clicks **Download Agent**.
3. Backend builds a custom `.exe` with Tauri.
4. Browser downloads the `.exe`.
5. User runs the `.exe`.
6. `.exe` opens a desktop window and asks for username/password.
7. `.exe` calls your backend:
   - `POST /login`
   - `POST /upload`
   - `POST /agents/{agent_id}/run`
8. Backend executes the agent and returns the response.

## Setup Requirements

### Backend

Install dependencies:

```powershell
cd c:\Users\VinaySaraswat\Downloads\agent\updated\Agent-Arena-Updated-Backend
pip install -r requirements.txt
pip install pyinstaller
```

Install desktop build tools:

```powershell
# Node dependencies for React + Tauri CLI
cd c:\Users\VinaySaraswat\Downloads\agent\updated\Agent-Arena-Updated-Frontend
npm install

# Rust/Cargo for Tauri
winget install Rustlang.Rustup
```

After installing Rust, close and reopen PowerShell, then verify:

```powershell
cargo --version
```

Your `.env` must include:

```env
LLM_PROVIDER=azure
AZURE_OPENAI_API_KEY=your-key
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_DEPLOYMENT_NAME=your-deployment-name
AZURE_OPENAI_API_VERSION=2024-12-01-preview

MONGO_URI=your-mongo-or-cosmos-uri
MONGO_DB_NAME=agent-platform-hq
SECRET_KEY=your-secret-key

# For production downloadable agents:
PUBLIC_API_BASE=https://your-backend-domain.com
```

For local testing, if `PUBLIC_API_BASE` is not set, the `.exe` uses the current backend URL, for example:

```text
http://127.0.0.1:8000
```

Run backend:

```powershell
uvicorn main:app --reload
```

### Frontend

Run frontend as usual:

```powershell
cd c:\Users\VinaySaraswat\Downloads\agent\updated\Agent-Arena-Updated-Frontend
npm install
npm run dev
```

For production frontend builds, set:

```env
VITE_API_BASE=https://your-backend-domain.com
```

## Important Production Setting

Before building `.exe` for real users, set this in backend `.env`:

```env
PUBLIC_API_BASE=https://your-backend-domain.com
```

Why this matters:

- Local testing can use `http://127.0.0.1:8000`.
- Customer machines cannot use your localhost.
- The `.exe` must know your hosted backend URL.

## How File Upload Works In The `.exe`

The `.exe` supports file-based agents like audit/report agents.

In the terminal app:

```text
[You]: attach C:\Users\Me\Downloads\audit.xlsx
[You]: analyze the attached file and create an audit report
```

Internally:

1. `.exe` uploads the local file to backend `/upload`.
2. Backend returns a server-side `file_path`.
3. `.exe` appends that file path to the query.
4. Backend agent sees the same style as the web app:

```text
(local path: C:\...\uploads\file.xlsx)
```

Supported commands in `.exe`:

```text
attach <file path>   Upload file to backend
files                List attached files
clear files          Clear file references
help                 Show commands
exit / quit          Exit
```

## Files Added

### Frontend `src-tauri/`

New Tauri desktop wrapper around the existing React frontend.

Purpose:

- Builds your existing `Agent-Arena-Updated-Frontend` as a Windows desktop `.exe`.
- Reuses the same React chat interface instead of a separate Tkinter/CMD UI.
- Opens directly into the downloaded agent flow after login.
- Uses env vars embedded at build time:
  - `VITE_API_BASE`
  - `VITE_DESKTOP_AGENT_ID`
  - `VITE_DESKTOP_AGENT_NAME`

Why added:

- End users should not use a command-line interface.
- The downloaded app should look like your real Agent Arena chat interface.
- Your backend code still stays on the server.

Files added:

```text
Agent-Arena-Updated-Frontend/src-tauri/Cargo.toml
Agent-Arena-Updated-Frontend/src-tauri/tauri.conf.json
Agent-Arena-Updated-Frontend/src-tauri/build.rs
Agent-Arena-Updated-Frontend/src-tauri/src/main.rs
Agent-Arena-Updated-Frontend/src-tauri/src/lib.rs
Agent-Arena-Updated-Frontend/src-tauri/capabilities/default.json
```

### `src/utils/desktopAgent.js`

Frontend helper for desktop mode.

Purpose:

- Reads `VITE_DESKTOP_AGENT_ID`.
- Reads `VITE_DESKTOP_AGENT_NAME`.
- Lets React know whether it is running as a downloaded desktop agent.

### `agent_runner_gui.py`

Older Tkinter GUI client.

Status:

- Kept for reference/debugging only.
- The customer-facing `.exe` now uses Tauri, not this file.

### `agent_runner_client.py`

Thin command-line client runner.

Purpose:

- Starts a terminal agent app.
- Loads `agent_client_config.json`.
- Logs in to backend using `/login`.
- Uploads files using `/upload`.
- Runs agent using `/agents/{agent_id}/run`.

Why kept:

- Useful for developer/debug testing.
- Not the main customer-facing runner.

### `DOWNLOADABLE_AGENT_SETUP.md`

This documentation file.

Purpose:

- Explains setup, flow, changed files, and troubleshooting.

### `core/orchestration/azure_settings.py`

Shared Azure OpenAI configuration helper.

Purpose:

- Normalizes Azure env vars.
- Supports `AZURE_OPENAI_DEPLOYMENT_NAME`.
- Gives clear error messages when config is missing.
- Helps both backend and portable tooling use the same LLM config pattern.

## Files Changed

### `main.py`

Changed export behavior.

Important functions:

- `_resolve_public_api_base()`
- `_build_portable_exe()`
- `/agents/{agent_id}/export`
- `/agents/export/file`

What changed:

- `.exe` export now builds the Tauri desktop frontend from `Agent-Arena-Updated-Frontend/src-tauri`.
- It sets `VITE_DESKTOP_AGENT_ID`, `VITE_DESKTOP_AGENT_NAME`, and `VITE_API_BASE` during the build.
- The `.exe` now shows your React chat interface.
- The `.exe` is still a thin backend client; it does not ship backend `core/`.
- Direct `/agents/{agent_id}/export` defaults to `format=exe`.
- ZIP/JSON are still technically available for developer/debug use, but not shown in customer UI.

### `requirements.txt`

Added:

```text
pyinstaller>=6.0.0
```

Why:

- Kept for fallback/debug builds.
- The main customer `.exe` path now uses Tauri, which requires Node.js + Rust/Cargo.

### `runner_stub.py`

Still exists for developer/offline testing, but it is no longer the customer-facing `.exe` runner.

Purpose now:

- Internal/dev portable runner.
- Can run locally with full `core/` folder.

For customer download, use Tauri:

```text
Agent-Arena-Updated-Frontend/src-tauri
```

### `src/services/api.js`

Changed frontend export API handling.

Important function:

```js
apiExportAgentExe(agentId)
```

What it does:

1. Calls backend:

```text
GET /agents/{agent_id}/export?format=exe
```

2. Backend builds `.exe` and returns:

```json
{
  "download_token": "...",
  "download_url": "/agents/export/file?token=..."
}
```

3. Browser downloads the file using native browser download.

Why:

- Large downloads should not be handled through JavaScript blob memory.

### `src/pages/AgentCatalog.jsx`

Changed UI.

What changed:

- Customer UI now shows only **Download Agent**.
- ZIP/JSON buttons were removed from normal agent cards.

### `src/pages/Chat.jsx`

Changed UI.

What changed:

- Download menu now exposes only **Download Agent (.exe)**.
- Removed ZIP/JSON from the customer-facing menu.

### `.env.example`

Updated env names.

Important:

Use:

```env
AZURE_OPENAI_DEPLOYMENT_NAME=...
```

not only:

```env
AZURE_OPENAI_DEPLOYMENT=...
```

## Backend API Endpoints

### Build `.exe`

```http
GET /agents/{agent_id}/export?format=exe
Authorization: Bearer <token>
```

Returns:

```json
{
  "status": "ready",
  "download_token": "...",
  "filename": "AgentName.exe",
  "download_url": "/agents/export/file?token=..."
}
```

### Download built `.exe`

```http
GET /agents/export/file?token=<download_token>
```

This endpoint is token-based so the browser can do a native file download.

## Local Testing Steps

1. Start backend:

```powershell
cd c:\Users\VinaySaraswat\Downloads\agent\updated\Agent-Arena-Updated-Backend
uvicorn main:app --reload
```

2. Start frontend:

```powershell
cd c:\Users\VinaySaraswat\Downloads\agent\updated\Agent-Arena-Updated-Frontend
npm run dev
```

3. Log in to web app.
4. Go to **My Agents**.
5. Click **Download Agent**.
6. Wait for build.
7. Run downloaded `.exe`.
8. A desktop app window opens.
9. Login in the `.exe` with the same username/password.
9. Ask:

```text
gave me latest news
```

10. For file agent:

Use the **Attach File** button, choose your file, then ask:

```text
analyze the attached file and create a report
```

## Production Deployment Notes

For real users:

```env
PUBLIC_API_BASE=https://api.yourdomain.com
ALLOWED_ORIGINS=https://app.yourdomain.com
```

The backend that builds `.exe` must be Windows if you want Windows `.exe` output.

Recommended hosting:

- Frontend: Azure Static Web Apps / Vercel / Netlify
- Backend: Windows App Service or Windows VM
- Database: Cosmos DB Mongo API or MongoDB Atlas

## Security Notes

The `.exe` does not include:

- Mongo URI
- Azure OpenAI key
- backend `core/` code
- tool implementation code
- full system prompts

The `.exe` does include:

- agent id
- agent name
- API base URL
- React desktop UI bundle

Users still need valid login credentials.

## Troubleshooting

### `.exe` opens but cannot connect

Check:

```env
PUBLIC_API_BASE=https://your-backend-domain.com
```

If it says `http://127.0.0.1:8000`, that only works on your own machine while backend is running locally.

### Login fails

Use the same username/password as the web app.

Backend must be running and reachable.

### File upload fails

Check:

- File exists on the user machine.
- Backend `/upload` works.
- User is logged in.
- Backend has write access to `uploads/`.

### Tauri/Rust missing

If export fails with `cargo is required` or `Rust/Cargo is required`, install Rust:

```powershell
winget install Rustlang.Rustup
```

Then close and reopen the terminal and verify:

```powershell
cargo --version
```

Also ensure frontend dependencies are installed:

```powershell
cd c:\Users\VinaySaraswat\Downloads\agent\updated\Agent-Arena-Updated-Frontend
npm install
```

### PyInstaller missing

Install:

```powershell
pip install pyinstaller
```

This is only needed for fallback/debug builds. Verify:

```powershell
python -m PyInstaller --version
```

### Browser downloads `.crdownload`

That means Chrome has not finished the download yet.

For the new thin `.exe`, file size should be small, around a few MB, so this should finish quickly.

### Windows SmartScreen warning

Unsigned `.exe` files may show a warning.

For production:

- Buy a code-signing certificate.
- Sign generated `.exe`.
- Optionally package with an installer.

## Current Recommended Product Behavior

Customer-facing:

```text
Download Agent (.exe)
```

Developer/debug only:

```text
ZIP
JSON blueprint
```

Do not expose ZIP/JSON to normal users because they reveal too much project structure.

