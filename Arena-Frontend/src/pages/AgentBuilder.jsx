import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAgent } from '../context/AgentContext';
import { useMcp } from '../context/McpContext';
import { 
  Save, CheckCircle2, Sparkles, ArrowLeft
} from 'lucide-react';
import Card from '../components/Card';
import Button from '../components/Button';
import { Input, Textarea } from '../components/FormInputs';
import AnimationPopup from '../components/AnimationPopup';
import AgentDNAEditor from '../components/AgentDNAEditor';
import { apiCreateAgent, apiPreviewAgent } from '../services/api';

export default function AgentBuilder() {
  const navigate = useNavigate();
  const { addAgent } = useAgent();
  const { builderTools = [], fetchBuilderTools } = useMcp();
  const [agentName, setAgentName] = useState('');
  const [purpose, setPurpose] = useState('');
  const [showAnimation, setShowAnimation] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);
  const [error, setError] = useState('');

  // Workflow steps: 'form' -> 'review'
  const [step, setStep] = useState('form');
  const [previewBlueprint, setPreviewBlueprint] = useState(null);
  const [createdAgent, setCreatedAgent] = useState(null);

  useEffect(() => {
    if (builderTools.length === 0 && typeof fetchBuilderTools === 'function') {
      fetchBuilderTools().catch(() => {});
    }
  }, [builderTools.length, fetchBuilderTools]);

  const handlePreview = async () => {
    if (!agentName.trim()) {
      alert("Please enter an Agent Name first.");
      return;
    }

    setError('');
    setIsProcessing(true);

    try {
      const result = await apiPreviewAgent(
        purpose || `General assistant named ${agentName}`,
        agentName
      );
      setPreviewBlueprint(result.blueprint);
      setStep('review');
    } catch (err) {
      console.error('Failed to generate preview:', err);
      setError(err.message || 'Failed to generate agent preview.');
    } finally {
      setIsProcessing(false);
    }
  };

  const handleFinalCreate = async () => {
    setError('');
    setIsProcessing(true);

    try {
      // Ensure we send the blueprint in the exact format the backend expects
      const finalBlueprint = { ...(previewBlueprint || {}) };

      // Build tool lookup map from builder catalog
      const catalogLookup = new Map();
      (builderTools || []).forEach(t => {
        const id = t.capability_id || t.id || t.name;
        const version = t.version || t.spec?.version || '1.0.0';
        if (id) catalogLookup.set(id, version);
        if (t.name) catalogLookup.set(t.name, version);
        if (t.capability_id) catalogLookup.set(t.capability_id, version);
        if (t.display_name) catalogLookup.set(t.display_name, version);
      });

      // Canonicalize tool IDs
      const rawTools = Array.isArray(finalBlueprint.tools) ? finalBlueprint.tools : [];
      const canonicalTools = [];
      const seenTools = new Set();
      
      for (const rawTool of rawTools) {
        if (!rawTool) continue;
        let toolId = String(rawTool).trim();
        const matchedTool = (builderTools || []).find(t => 
          t.capability_id === toolId || 
          t.id === toolId || 
          t.name === toolId || 
          t.display_name === toolId ||
          (t.name && t.name.toLowerCase() === toolId.toLowerCase())
        );
        if (matchedTool) {
          toolId = matchedTool.capability_id || matchedTool.id || matchedTool.name;
        }
        if (toolId && !seenTools.has(toolId)) {
          seenTools.add(toolId);
          canonicalTools.push(toolId);
        }
      }

      // Construct synchronized, unique tool_refs matching canonicalTools exactly
      const toolRefs = [];
      const seenRefIds = new Set();
      for (const toolId of canonicalTools) {
        if (seenRefIds.has(toolId)) continue;
        seenRefIds.add(toolId);
        
        let version = catalogLookup.get(toolId) || (
          Array.isArray(finalBlueprint.tool_refs)
            ? finalBlueprint.tool_refs.find(r => r.tool_id === toolId)?.version
            : null
        );
        
        if (!version && Array.isArray(finalBlueprint.tool_metadata)) {
          version = finalBlueprint.tool_metadata.find(m => (m.tool_id === toolId || m.name === toolId))?.version;
        }

        if (!version) {
          const matchedTool = (builderTools || []).find(t => (t.capability_id || t.id || t.name) === toolId);
          version = matchedTool?.version || matchedTool?.spec?.version || '1.0.0';
        }

        toolRefs.push({
          tool_id: toolId,
          version: version || '1.0.0',
        });
      }

      finalBlueprint.tools = canonicalTools;
      finalBlueprint.tool_refs = toolRefs;

      // Clean up crew_roles assigned_tools
      if (Array.isArray(finalBlueprint.crew_roles)) {
        finalBlueprint.crew_roles = finalBlueprint.crew_roles.map(role => ({
          ...role,
          assigned_tools: Array.from(new Set(
            (role.assigned_tools || [])
              .map(t => {
                const matched = (builderTools || []).find(bt => 
                  bt.capability_id === t || bt.id === t || bt.name === t || bt.display_name === t
                );
                return matched ? (matched.capability_id || matched.id || matched.name) : t;
              })
              .filter(t => seenTools.has(t))
          )),
        }));
      }

      // Clean up tool_governance
      if (finalBlueprint.tool_governance && typeof finalBlueprint.tool_governance === 'object') {
        const cleanedGovernance = {};
        for (const [key, policy] of Object.entries(finalBlueprint.tool_governance)) {
          if (seenTools.has(key)) {
            cleanedGovernance[key] = policy;
          }
        }
        finalBlueprint.tool_governance = cleanedGovernance;
      }

      const result = await apiCreateAgent(null, null, finalBlueprint);
      
      const blueprint = result.config || result.blueprint || previewBlueprint || {};
      setCreatedAgent({
        id: result.id || result._id || result.agent_id || blueprint.id,
        agent_id: result.agent_id || result.id || result._id || blueprint.agent_id,
        name: result.name || blueprint.name || agentName,
        purpose: result.description || blueprint.user_intent || purpose || 'General assistance',
        capability: blueprint.domain || 'General',
        tone: 'Professional',
        status: result.status || 'Active',
        createdAt: result.created_at || new Date().toISOString(),
        interactions: 0,
        agent_kind: result.agent_kind || 'custom',
        understanding: blueprint.understanding || `Optimized AI role interpretation for ${agentName}.`,
        _blueprint: { ...blueprint, ...result },
      });

      setShowAnimation(true);
    } catch (err) {
      console.error('Agent deployment failed:', err);
      setError(err.message || 'Failed to deploy agent.');
    } finally {
      setIsProcessing(false);
    }
  };

  const onAnimationComplete = () => {
    setShowAnimation(false);
    if (createdAgent) {
      addAgent(createdAgent);
    }
    navigate('/catalog');
  };

  if (step === 'review') {
    return (
      <div className="fixed inset-0 z-50 flex flex-col h-[100dvh] w-full bg-white animate-in fade-in duration-500">
        {showAnimation && <AnimationPopup onComplete={onAnimationComplete} />}
        <AgentDNAEditor
          fullScreen
          config={previewBlueprint}
          isNew={true}
          onChange={setPreviewBlueprint}
          onCancel={() => setStep('form')}
          onConfirm={handleFinalCreate}
        />
      </div>
    );
  }

  return (
    <div className="min-h-full py-16 px-6 flex items-center justify-center animate-in fade-in duration-700 bg-section-bg/30">
      {showAnimation && <AnimationPopup onComplete={onAnimationComplete} />}
      
      <div className="w-full max-w-[900px]">
        {/* ─── MAIN BUILDER CARD ─────────────────────────────────────── */}
        <div className="bg-white border border-border/50 rounded-[2.5rem] p-12 lg:p-14 shadow-[0_20px_50px_rgba(0,0,0,0.02)] relative overflow-hidden">
          {/* Top Decorative Border */}
          <div className="absolute top-0 left-0 w-full h-1 bg-gradient-to-r from-transparent via-primary/20 to-transparent"></div>
          
          {/* CARD HEADER: Title & Create Button */}
          <div className="flex items-start justify-between mb-12">
            <div className="space-y-2">
              <div className="inline-flex px-3 py-1 bg-primary/5 border border-primary/10 rounded-full text-[10px] font-black text-primary tracking-[0.15em] uppercase">
                Step 1: Define Intent
              </div>
              <h1 className="text-3xl font-black text-text-primary tracking-tight">Build Your AI Assistant</h1>
              <p className="text-sm text-text-secondary font-medium leading-relaxed max-w-sm">
                Describe your assistant and its mission. We'll architect its DNA for your review.
              </p>
            </div>
            
            <Button 
              onClick={handlePreview} 
              disabled={isProcessing}
              className="px-8 py-4 bg-primary hover:bg-primary-hover text-white rounded-xl shadow-lg shadow-primary/10 transition-all hover:scale-105 active:scale-95 font-bold text-sm flex items-center gap-2"
            >
              <Sparkles size={16} /> {isProcessing ? 'Architecting...' : 'Generate DNA'}
            </Button>
          </div>

          {error && (
            <div className="mb-6 p-4 bg-red-50 border border-red-100 rounded-2xl text-sm text-red-600 font-medium">
              {error}
            </div>
          )}

          <div className="space-y-9">
            {/* FIELD: Agent Name */}
            <div className="space-y-3">
              <label htmlFor="agentName" className="text-[13px] font-bold text-text-primary/70 ml-1 uppercase tracking-wider">
                Agent Name
              </label>
              <div className="relative group">
                <Input 
                  id="agentName"
                  placeholder="e.g. Procurement Assistant" 
                  value={agentName} 
                  onChange={(e) => setAgentName(e.target.value)} 
                  className="h-[60px] px-6 text-base font-semibold rounded-2xl border-border/60 focus:border-primary/40 focus:ring-8 focus:ring-primary/5 transition-all bg-section-bg/30 placeholder:text-text-secondary/30"
                />
                <div className="absolute right-5 top-1/2 -translate-y-1/2 text-primary/20 group-focus-within:text-primary transition-colors">
                  <CheckCircle2 size={20} />
                </div>
              </div>
            </div>

            {/* FIELD: Agent Instructions */}
            <div className="space-y-3">
              <label htmlFor="purpose" className="text-[13px] font-bold text-text-primary/70 ml-1 uppercase tracking-wider">
                Agent Instructions
              </label>
              <div className="relative">
                <Textarea 
                  id="purpose"
                  placeholder="Describe what this AI assistant should do, how it should behave, and what tasks it should help with. For example: 'A procurement agent that collects vendor quotes, compares prices, and sends RFP emails to selected vendors.'" 
                  value={purpose} 
                  onChange={(e) => setPurpose(e.target.value)} 
                  className="min-h-[240px] p-6 text-base font-semibold leading-relaxed rounded-2xl border-border/60 focus:border-primary/40 focus:ring-8 focus:ring-primary/5 transition-all bg-section-bg/30 resize-none placeholder:text-text-secondary/30"
                />
              </div>
              <div className="flex items-center gap-2 ml-1 mt-2">
                <div className="p-1 bg-primary/10 rounded">
                  <Sparkles size={10} className="text-primary" />
                </div>
                <p className="text-xs text-text-secondary font-bold tracking-tight">
                  Next Step: Review the architected multi-agent workforce and custom tools.
                </p>
              </div>
            </div>
          </div>
        </div>
        
        {/* Subtle Footer Branding */}
        <div className="mt-12 flex items-center justify-center gap-4 opacity-20">
          <div className="h-[1px] w-16 bg-text-primary"></div>
          <p className="text-[10px] font-black uppercase tracking-[0.3em] text-text-primary">
            Meridian AI Workspace Engine
          </p>
          <div className="h-[1px] w-16 bg-text-primary"></div>
        </div>
      </div>
    </div>
  );
}
