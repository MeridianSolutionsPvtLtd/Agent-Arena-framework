import React from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Cpu, Settings, Cloud, Shield, TrendingUp, Headphones, BarChart3,
  CheckCircle2, ArrowRight, ChevronRight, Users, Globe, Zap, Bot, MessageSquare
} from 'lucide-react';
import Button from '../components/Button';
import Card from '../components/Card';
import { services, solutions, whyChooseUs } from '../data/mockData';

const iconMap = {
  Cpu, Settings, Cloud, Shield, TrendingUp, Headphones, BarChart3,
};

import { useAuth } from '../context/AuthContext';

export default function LandingPage() {
  const navigate = useNavigate();
  const { isAuthenticated } = useAuth();

  const handleProtectedClick = (e, path) => {
    e.preventDefault();
    if (isAuthenticated) {
      navigate(path);
    } else {
      navigate('/login');
    }
  };

  return (
    <>
      {/* ─── Hero Section ────────────────────────── */}
      <section className="bg-white pt-6 pb-20 lg:pt-8 lg:pb-32 overflow-hidden">
        <div className="section-container">
          <div className="grid lg:grid-cols-2 gap-16 items-center">
            
            {/* Left Column — Text Content */}
            <div className="space-y-6 max-w-2xl animate-in slide-in-from-left duration-700">
              <div className="inline-flex items-center gap-2 px-4 py-2 bg-light-blue text-primary text-xs font-black rounded-full uppercase tracking-widest shadow-sm">
                <Zap size={14} className="fill-primary" />
                Enterprise AI OS
              </div>
              <h1 className="text-5xl lg:text-7xl font-black text-text-primary leading-[1.05] tracking-tight">
                Build Intelligent <span className="text-primary">AI Agents</span> In Minutes
              </h1>
              <p className="text-lg lg:text-xl text-text-secondary leading-relaxed font-medium max-w-lg">
                Meridian AI delivers production-ready AI agents that automate workflows, 
                enhance decision-making, and integrate seamlessly with enterprise infrastructure.
              </p>
            </div>

            {/* Right Column — Visual Area */}
            <div className="relative animate-in zoom-in duration-1000 delay-200">
              <div className="relative z-10 bg-gradient-to-br from-light-blue/20 to-white p-4 rounded-[3rem] border border-border/40 shadow-2xl">
                <img 
                  src="/hero-visual.png" 
                  alt="Enterprise AI Visual" 
                  className="w-full h-auto rounded-[2.5rem] shadow-inner"
                />
              </div>
              
              {/* Subtle background glow */}
              <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[120%] h-[120%] bg-primary/5 blur-[100px] -z-0"></div>
            </div>

          </div>
        </div>
      </section>

      {/* ─── Services Section ────────────────────── */}
      <section id="services" className="bg-section-bg py-20 scroll-mt-20">
        <div className="section-container">
          <div className="text-center max-w-2xl mx-auto mb-14">
            <p className="text-sm font-semibold text-primary uppercase tracking-wider mb-3">Our Services</p>
            <h2 className="text-3xl lg:text-4xl font-extrabold text-text-primary mb-4">
              Comprehensive AI Solutions for Enterprise
            </h2>
            <p className="text-text-secondary leading-relaxed">
              From automation to compliance, our suite of AI services is designed to meet the complex needs of modern enterprise organizations.
            </p>
          </div>

          <div className="grid md:grid-cols-2 lg:grid-cols-4 gap-6">
            {services.map((service) => {
              const Icon = iconMap[service.icon];
              return (
                <Card key={service.id} className="text-center group">
                  <div className="w-12 h-12 mx-auto mb-4 bg-light-blue rounded-xl flex items-center justify-center group-hover:bg-primary transition-colors duration-300">
                    <Icon size={24} className="text-primary group-hover:text-white transition-colors duration-300" />
                  </div>
                  <h3 className="text-base font-bold text-text-primary mb-2">{service.title}</h3>
                  <p className="text-sm text-text-secondary leading-relaxed">{service.description}</p>
                </Card>
              );
            })}
          </div>
        </div>
      </section>

      {/* ─── AI Workflow Section ─────────────────── */}
      <section id="workflow" className="bg-white py-24 scroll-mt-20">
        <div className="section-container">
          <div className="text-center max-w-3xl mx-auto mb-20">
            <p className="text-sm font-black text-primary uppercase tracking-[0.2em] mb-4">AI Workflow</p>
            <h2 className="text-4xl lg:text-5xl font-extrabold text-text-primary mb-6 tracking-tight">
              Build Your AI Assistant
            </h2>
            <p className="text-text-secondary text-lg leading-relaxed font-medium">
              Create, configure, deploy, and interact with intelligent AI agents in minutes.
            </p>
          </div>

          <div className="relative">
            {/* Connector Line (Desktop) */}
            <div className="hidden lg:block absolute top-1/2 left-0 w-full h-px bg-gradient-to-r from-transparent via-border to-transparent -translate-y-12"></div>
            
            <div className="grid md:grid-cols-2 lg:grid-cols-4 gap-8 relative z-10">
              {[
                {
                  step: 'STEP 1',
                  title: 'Describe Your AI',
                  description: 'Describe what your AI assistant should do using natural language instructions.',
                  icon: MessageSquare,
                },
                {
                  step: 'STEP 2',
                  title: 'Configure Intelligence',
                  description: 'Customize behavior, personality, and knowledge sources to match your workflow.',
                  icon: Settings,
                },
                {
                  step: 'STEP 3',
                  title: 'Create & Deploy',
                  description: 'Instantly generate your AI assistant and deploy it into your workspace.',
                  icon: Cpu,
                },
                {
                  step: 'STEP 4',
                  title: 'Chat & Monitor',
                  description: 'Interact with your AI assistant in real-time while monitoring intelligent activity.',
                  icon: Bot,
                }
              ].map((item, idx) => (
                <div key={idx} className="group flex flex-col items-center">
                  <div className="bg-white border border-border/60 p-8 rounded-[2rem] shadow-sm hover:shadow-xl hover:shadow-primary/5 transition-all duration-500 flex flex-col h-full w-full relative">
                    <div className="w-14 h-14 bg-light-blue rounded-2xl flex items-center justify-center mb-8 group-hover:bg-primary group-hover:scale-110 transition-all duration-300 shadow-sm border border-primary/5">
                      <item.icon size={28} className="text-primary group-hover:text-white transition-colors duration-300" />
                    </div>
                    
                    <div className="inline-flex px-3 py-1 bg-section-bg border border-border rounded-full text-[10px] font-black text-text-secondary tracking-widest mb-4 w-fit">
                      {item.step}
                    </div>
                    
                    <h3 className="text-xl font-bold text-text-primary mb-4 tracking-tight">{item.title}</h3>
                    <p className="text-sm text-text-secondary leading-relaxed font-medium">{item.description}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>




    </>
  );
}
