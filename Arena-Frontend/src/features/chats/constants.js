// Slice-1 (text chat) constants for the persona-chat feature.
//
// DEFAULT_MODEL is null on purpose. /api/openai/chat uses the request `model`
// directly as the Azure *deployment* name (Agent-Integration/services/openai_service.py:
// `deployment_name = model or settings.AZURE_OPENAI_DEPLOYMENT_NAME`). This unified
// backend's Azure resource exposes the deployment set in AZURE_OPENAI_DEPLOYMENT_NAME
// (currently "gpt-4o-aiteam"), NOT Arena's "gpt-4o-mini-km" (which 404s as
// DeploymentNotFound). Sending null lets the backend fall back to its own configured
// deployment, keeping the frontend decoupled from infra naming. Model switching (with
// names that map to real deployments) arrives in Slice 2.
export const DEFAULT_MODEL = null;
export const DEFAULT_SYSTEM_PROMPT = 'You are a helpful AI assistant.';

// How many trailing messages are sent to the model as context (matches Arena's slice(-7)).
export const CONTEXT_WINDOW = 7;

// Starter prompts shown on an empty thread; clicking one prefills the composer.
export const SUGGESTIONS = [
  'Summarize the key points of a document I paste in.',
  'Draft a professional email declining a meeting.',
  'Explain a complex topic in simple terms.',
  'Brainstorm names for a new internal tool.',
];
