import React, { useState, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { Search, Filter, Trash2, ArrowRight, Bot, ChevronDown, Check, Download, Loader2 } from 'lucide-react';
import Button from '../components/Button';
import Card from '../components/Card';
import Badge from '../components/Badge';
import { useAgent } from '../context/AgentContext';
import { apiExportAgentExe } from '../services/api';
import { Skeleton, SkeletonAgentCard } from '../components/skeleton';

export default function AgentCatalog() {
  const navigate = useNavigate();
  const { agents, loading, deleteAgent } = useAgent();
  const [search, setSearch] = useState('');
  const [selectedCapability, setSelectedCapability] = useState('All');
  const [agentToDelete, setAgentToDelete] = useState(null);
  const [isDropdownOpen, setIsDropdownOpen] = useState(false);
  const [exportingId, setExportingId] = useState(null);
  const [exportError, setExportError] = useState('');

  const handleExportExe = async (agent) => {
    setExportError('');
    setExportingId(`${agent.id}-exe`);
    try {
      await apiExportAgentExe(agent.id);
    } catch (err) {
      setExportError(err.message || 'Portable app build failed');
    } finally {
      setExportingId(null);
    }
  };

  const capabilities = ['All', ...Array.from(new Set(agents.map(a => a.capability)))];

  const filtered = useMemo(() => {
    return agents.filter((agent) => {
      const matchSearch = agent.name.toLowerCase().includes(search.toLowerCase()) ||
        agent.purpose.toLowerCase().includes(search.toLowerCase());
      const matchCap = selectedCapability === 'All' || agent.capability === selectedCapability;
      return matchSearch && matchCap;
    });
  }, [search, selectedCapability, agents]);

  const formatDate = (isoString) => {
    return new Date(isoString).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
  };

  return (
    <div className="min-h-screen bg-section-bg">
      <div className="bg-white border-b border-border">
        <div className="section-container py-8">
          <div className="flex items-end justify-between">
            <div>
              <h1 className="text-3xl font-black text-text-primary tracking-tight mb-2">My Agents</h1>
              <p className="text-text-secondary font-medium">Manage and interact with your deployed AI agents.</p>
            </div>
            <div className="px-4 py-2 bg-primary/5 border border-primary/10 rounded-2xl flex items-center gap-2">
              <span className="text-[10px] font-black text-primary uppercase tracking-widest">Active Registry</span>
              <div className="w-1.5 h-1.5 bg-primary rounded-full animate-pulse"></div>
              {loading ? (
                <Skeleton variant="rounded" className="h-4 w-16" />
              ) : (
                <span className="text-xs font-black text-text-primary">{filtered.length} Agents</span>
              )}
            </div>
          </div>
        </div>
      </div>

      <div className="section-container py-8 min-h-[calc(100vh-200px)]">
        {/* Horizontal Search & Filter Bar */}
        <div className="flex flex-col md:flex-row gap-4 items-center mb-10 bg-white p-2 rounded-2xl border border-border/40 shadow-sm relative z-20">
          <div className="relative flex-1 min-w-0">
            <Search size={18} className="absolute left-5 top-1/2 -translate-y-1/2 text-text-secondary" />
            <input
              type="text"
              placeholder="Search by agent name, capability, or purpose..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="w-full pl-14 pr-4 py-4 bg-transparent border-none rounded-xl text-sm font-medium focus:ring-0 outline-none transition-all placeholder:text-text-secondary/40"
            />
          </div>
          
          <div className="flex items-center gap-2 p-2 shrink-0">
            <div className="relative">
              <button 
                onClick={() => setIsDropdownOpen(!isDropdownOpen)}
                className={`
                  flex items-center gap-3 px-5 py-3 rounded-xl border transition-all cursor-pointer min-w-[220px]
                  ${isDropdownOpen 
                    ? 'bg-white border-primary shadow-lg shadow-primary/5 ring-4 ring-primary/5' 
                    : 'bg-section-bg border-border/20 hover:border-primary/30'
                  }
                `}
              >
                <Filter size={14} className={isDropdownOpen ? 'text-primary' : 'text-primary opacity-70'} />
                <div className="w-px h-4 bg-border/40"></div>
                <span className="text-[10px] font-black uppercase tracking-widest text-text-primary flex-1 text-left truncate">
                  {selectedCapability} Capability
                </span>
                <ChevronDown size={14} className={`text-text-secondary transition-transform duration-300 ${isDropdownOpen ? 'rotate-180' : ''}`} />
              </button>

              {isDropdownOpen && (
                <>
                  <div 
                    className="fixed inset-0 z-40" 
                    onClick={() => setIsDropdownOpen(false)}
                  ></div>
                  <div className="absolute left-0 right-0 top-[calc(100%+8px)] bg-white backdrop-blur-xl border border-border/60 rounded-2xl shadow-2xl py-3 z-50 animate-in fade-in zoom-in-95 slide-in-from-top-2 duration-200">
                    <div className="px-5 py-2 mb-2 border-b border-border/10">
                      <p className="text-[9px] font-black text-text-secondary uppercase tracking-widest">Select Capability</p>
                    </div>
                    <div className="max-h-[300px] overflow-y-auto px-2 space-y-1 custom-scrollbar">
                      {capabilities.map((cat) => (
                        <button
                          key={cat}
                          onClick={() => {
                            setSelectedCapability(cat);
                            setIsDropdownOpen(false);
                          }}
                          className={`
                            w-full text-left px-4 py-3 rounded-xl text-[11px] font-bold transition-all flex items-center justify-between group/item
                            ${selectedCapability === cat 
                              ? 'bg-primary text-white shadow-md shadow-primary/20' 
                              : 'text-text-primary hover:bg-primary/5'
                            }
                          `}
                        >
                          <span className="uppercase tracking-wide leading-tight">{cat}</span>
                          {selectedCapability === cat && <Check size={12} className="shrink-0 ml-2" />}
                        </button>
                      ))}
                    </div>
                  </div>
                </>
              )}
            </div>
            
            <div className="min-w-fit flex items-center">
              {(search || selectedCapability !== 'All') && (
                <button 
                  onClick={() => { setSearch(''); setSelectedCapability('All'); }}
                  className="px-4 py-3 text-[10px] font-black uppercase tracking-widest text-primary hover:bg-primary/5 rounded-xl transition-all whitespace-nowrap animate-in fade-in slide-in-from-right-2 duration-200"
                >
                  Clear Results
                </button>
              )}
            </div>
          </div>
        </div>

        {exportError && (
          <div className="mb-6 p-4 rounded-xl bg-red-50 border border-red-100 text-sm text-red-700 font-medium">
            {exportError}
          </div>
        )}

        <div className="flex gap-8 items-start">
          {/* Sidebar Filters Removed */}

          {/* Agent Grid */}
          <div className="flex-1">
            <div className="grid md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4 gap-6">
              {loading ? (
                <>
                  <SkeletonAgentCard variant="catalog" />
                  <SkeletonAgentCard variant="catalog" />
                  <SkeletonAgentCard variant="catalog" />
                  <SkeletonAgentCard variant="catalog" />
                  <SkeletonAgentCard variant="catalog" />
                  <SkeletonAgentCard variant="catalog" />
                </>
              ) : filtered.length > 0 ? (
                filtered.map((agent) => (
                  <Card key={agent.id} className="flex flex-col relative group transition-all hover:border-primary/40 hover:shadow-xl">
                    <div className="flex items-start justify-between mb-4">
                      <div className="w-10 h-10 rounded-lg bg-primary/5 text-primary flex items-center justify-center">
                        <Bot size={22} className="opacity-80" />
                      </div>
                      <div className="flex items-center gap-2">
                        <Badge variant="primary" className="capitalize">{agent.capability}</Badge>
                        <Badge variant="success">Active</Badge>
                      </div>
                    </div>

                    <h3 className="text-base font-bold text-text-primary mb-1">{agent.name}</h3>
                    <p className="text-sm text-text-secondary leading-relaxed mb-4 flex-1 line-clamp-3">
                      {agent.purpose}
                    </p>

                    <div className="mb-4 text-xs text-text-secondary">
                      <div className="flex items-center gap-2 bg-section-bg/50 p-2 rounded-lg border border-border/30">
                        <span className="text-text-primary/50 font-bold uppercase tracking-tighter text-[9px]">Deployed</span>
                        <div className="w-1 h-1 bg-border rounded-full"></div>
                        {/* <span className="font-medium text-text-primary">{formatDate(agent.createdAt)}</span> */}
                      </div>
                    </div>

                    <div className="pt-4 border-t border-border space-y-3">
                      <div className="flex items-center justify-between">
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            setAgentToDelete(agent);
                          }}
                          className="flex items-center gap-2 px-3 py-2 text-[10px] font-black uppercase tracking-widest text-text-secondary hover:text-red-500 hover:bg-red-50 border border-transparent hover:border-red-100 rounded-xl transition-all cursor-pointer"
                        >
                          <span>Delete</span>
                          <Trash2 size={14} />
                        </button>
                        <Button
                          size="sm"
                          className="rounded-xl px-5 py-2.5 font-black text-[10px] uppercase tracking-widest shadow-lg shadow-primary/10"
                          onClick={() => navigate(`/chat/${agent.id}`)}
                        >
                          Workspace
                          <ArrowRight size={14} />
                        </Button>
                      </div>
                    </div>
                  </Card>
                ))
              ) : null}
            </div>

            {!loading && filtered.length === 0 && (
              <div className="text-center py-16 bg-white border border-border rounded-xl mt-4">
                <p className="text-text-secondary mb-4">You haven't created any agents yet.</p>
                <Button onClick={() => navigate('/builder')}>Create New Agent</Button>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* ─── DELETE CONFIRMATION MODAL ─── */}
      {agentToDelete && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm animate-in fade-in duration-300">
          <div className="bg-white rounded-[2.5rem] p-10 max-w-md w-full shadow-2xl border border-border/40 animate-in zoom-in-95 duration-300">
            <div className="w-16 h-16 bg-red-50 rounded-2xl flex items-center justify-center text-red-500 mx-auto mb-6 border border-red-100">
              <Trash2 size={32} />
            </div>
            <h2 className="text-2xl font-black text-text-primary text-center mb-3 tracking-tight">Decommission Agent?</h2>
            <p className="text-sm text-text-secondary text-center mb-8 font-medium leading-relaxed">
              Are you sure you want to delete <span className="text-text-primary font-black">"{agentToDelete.name}"</span>?
              This action is irreversible and will purge all associated telemetry and DNA configurations.
            </p>
            <div className="flex gap-4">
              <button
                onClick={() => setAgentToDelete(null)}
                className="flex-1 px-6 py-4 rounded-2xl bg-section-bg text-text-secondary font-black text-xs uppercase tracking-widest hover:bg-border/40 transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={() => {
                  deleteAgent(agentToDelete.id);
                  setAgentToDelete(null);
                }}
                className="flex-1 px-6 py-4 rounded-2xl bg-red-500 text-white font-black text-xs uppercase tracking-widest hover:bg-red-600 shadow-lg shadow-red-500/20 transition-all active:scale-95"
              >
                Confirm Delete
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
