import React from 'react';
import { useNavigate } from 'react-router-dom';
import { Plus, Bot, Activity, ArrowRight, Clock, ShieldCheck, Zap, BarChart3 } from 'lucide-react';
import Card from '../components/Card';
import Button from '../components/Button';
import Badge from '../components/Badge';
import { useAgent } from '../context/AgentContext';
import { SkeletonStatCard, SkeletonAgentCard } from '../components/skeleton';

export default function Dashboard() {
  const navigate = useNavigate();
  const { agents, loading } = useAgent();

  const stats = [
    { id: 1, label: 'Active Deployments', value: agents.length.toString(), change: 'Live Agents', icon: Bot, color: 'text-primary' },
    { id: 2, label: 'Compute Status', value: 'Optimal', icon: Zap, color: 'text-amber-500' },
    { id: 3, label: 'Security Layer', value: 'Active', icon: ShieldCheck, color: 'text-green-600' },
  ];

  return (
    <div className="max-w-7xl mx-auto px-6 py-12 animate-in fade-in duration-1000">
      
      {/* ─── HERO SECTION ────────────────────────────────────────── */}
      <div className="mb-12 flex flex-col md:flex-row md:items-end justify-between gap-6">
        <div className="space-y-2">
          <div className="inline-flex items-center gap-2 px-3 py-1 bg-primary/5 border border-primary/10 rounded-full text-[10px] font-black text-primary tracking-widest uppercase">
            <ShieldCheck size={12} />
            Enterprise Workspace
          </div>
          <h1 className="text-4xl font-black text-text-primary tracking-tight">Intelligence Command</h1>
          <p className="text-text-secondary font-medium max-w-xl">
            Orchestrate your autonomous agent workforce and monitor real-time decision telemetry across your organization.
          </p>
        </div>
        
        <Button 
          onClick={() => navigate('/builder')} 
          className="rounded-2xl px-8 py-4 shadow-xl shadow-primary/20 hover:scale-105 active:scale-95 transition-all font-black text-xs uppercase tracking-widest"
        >
          <Plus size={18} /> Deploy New Agent
        </Button>
      </div>

      {/* ─── STATS GRID ─────────────────────────────────────────── */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-12">
        {loading ? (
          <>
            <SkeletonStatCard />
            <SkeletonStatCard />
            <SkeletonStatCard />
          </>
        ) : (
          stats.map((stat) => (
            <Card key={stat.id} className="p-8 border-border/40 bg-white relative overflow-hidden group hover:shadow-xl hover:shadow-primary/5 transition-all duration-500">
              <div className="absolute -right-4 -bottom-4 opacity-5 group-hover:opacity-10 transition-opacity">
                <stat.icon size={120} />
              </div>
              <div className="relative z-10">
                <div className="flex items-center justify-between mb-4">
                  <div className={`p-2.5 rounded-xl bg-section-bg border border-border/40 ${stat.color}`}>
                    <stat.icon size={20} />
                  </div>
                  <Badge variant="secondary" className="bg-section-bg text-[10px] uppercase font-black tracking-tighter">System</Badge>
                </div>
                <p className="text-[11px] font-black text-text-secondary/50 uppercase tracking-[0.2em] mb-1">{stat.label}</p>
                <h3 className="text-3xl font-black text-text-primary tracking-tighter">{stat.value}</h3>
                <p className="text-[10px] text-primary font-bold mt-3 uppercase tracking-widest">{stat.change}</p>
              </div>
            </Card>
          ))
        )}
      </div>

      <div className="space-y-6">
        <div className="flex items-center justify-between px-2">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-primary/10 text-primary rounded-lg shadow-sm">
              <Activity size={18} />
            </div>
            <h2 className="text-xl font-black text-text-primary tracking-tight">Active Registries</h2>
          </div>
          <button onClick={() => navigate('/catalog')} className="text-xs font-bold text-primary hover:underline flex items-center gap-1.5">
            View Catalog <ArrowRight size={14} />
          </button>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">
          {loading ? (
            <>
              <SkeletonAgentCard variant="dashboard" />
              <SkeletonAgentCard variant="dashboard" />
              <SkeletonAgentCard variant="dashboard" />
            </>
          ) : agents.length > 0 ? (
            agents.map((agent) => (
              <div 
                key={agent.id} 
                onClick={() => navigate(`/chat/${agent.id}`)}
                className="flex flex-col p-8 bg-white border border-border/60 rounded-[2.5rem] hover:border-primary/30 hover:shadow-2xl hover:shadow-primary/10 transition-all duration-500 group cursor-pointer relative overflow-hidden"
              >
                <div className="absolute -right-4 -top-4 opacity-[0.03] group-hover:opacity-[0.08] group-hover:scale-110 transition-all duration-700">
                  <Bot size={120} />
                </div>

                <div className="flex items-start justify-between mb-8">
                  <div className="w-14 h-14 bg-section-bg border border-border/60 rounded-2xl flex items-center justify-center text-primary font-black text-xl shadow-sm group-hover:scale-110 group-hover:rotate-3 transition-all duration-500">
                    {agent.name.charAt(0).toUpperCase()}
                  </div>
                  <div className="flex items-center gap-1.5 px-3 py-1 bg-green-50 text-[10px] font-black text-green-600 rounded-full border border-green-100 uppercase tracking-widest shadow-sm">
                    <div className="w-1.5 h-1.5 bg-green-500 rounded-full animate-pulse"></div>
                    Live
                  </div>
                </div>

                <div className="flex-1 min-w-0 mb-6">
                  <h4 className="font-black text-text-primary text-xl mb-2 truncate tracking-tight group-hover:text-primary transition-colors">{agent.name}</h4>
                  <p className="text-sm text-text-secondary/70 font-medium line-clamp-2 leading-relaxed h-10">{agent.purpose}</p>
                </div>

                <div className="flex items-center justify-between pt-6 border-t border-border/40">
                  <div className="flex items-center gap-2 text-[10px] font-black text-text-secondary/40 uppercase tracking-widest">
                    <Clock size={14} className="text-primary/40" />
                    {new Date(agent.createdAt).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}
                  </div>
                  <div className="text-primary opacity-0 group-hover:opacity-100 group-hover:translate-x-1 transition-all">
                    <ArrowRight size={18} />
                  </div>
                </div>
              </div>
            ))
          ) : (
            <div className="col-span-full py-24 text-center border-2 border-dashed border-border/60 rounded-[3rem] bg-section-bg/30">
              <div className="w-20 h-20 bg-white border border-border/60 rounded-3xl flex items-center justify-center mx-auto mb-6 text-text-secondary/20">
                <Bot size={40} />
              </div>
              <h3 className="text-xl font-bold text-text-primary mb-2">No custom agents found</h3>
              <p className="text-text-secondary mb-8 max-w-xs mx-auto font-medium">Start by creating your first AI assistant to see it here.</p>
              <Button onClick={() => navigate('/builder')} className="rounded-xl px-10">Deploy Agent</Button>
            </div>
          )}
        </div>
      </div>

    </div>
  );
}
