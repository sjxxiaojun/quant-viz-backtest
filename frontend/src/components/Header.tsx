import React from 'react';
import { BrainCircuit, LayoutDashboard, Activity, PieChart, GitCompare, BarChart3, Play } from 'lucide-react';
import { cn } from '../utils';

interface HeaderProps {
  view: 'mall' | 'console' | 'dashboard' | 'compare' | 'factorLab' | 'virtualTrade';
  setView: (v: 'mall' | 'console' | 'dashboard' | 'compare' | 'factorLab' | 'virtualTrade') => void;
}

export function Header({ view, setView }: HeaderProps) {
  return (
    <header className="flex flex-col md:flex-row justify-between items-start md:items-center gap-6">
      <div className="space-y-1">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 bg-blue-600 rounded-xl flex items-center justify-center shadow-lg shadow-blue-900/20">
            <BrainCircuit className="text-white w-6 h-6" />
          </div>
          <h1 className="text-3xl font-black tracking-tighter text-blue-500 cursor-pointer" onClick={() => setView('mall')}>
            Gemini量化pro
          </h1>
        </div>
        <p className="text-slate-500 font-medium ml-13 italic text-xs">集成机器学习与全市场数据的专业量化平台</p>
      </div>
      
      <nav className="flex gap-2 p-1 rounded-2xl backdrop-blur-xl shadow-2xl" style={{ background: 'rgba(13, 27, 50, 0.6)', borderWidth: '1px', borderStyle: 'solid', borderColor: 'rgba(59, 130, 246, 0.1)' }}>
        <button 
          onClick={() => setView('mall')}
          className={cn(
            "px-6 py-2 rounded-xl text-xs font-bold transition-all flex items-center gap-2",
            view === 'mall' ? "bg-blue-600 text-white shadow-lg shadow-blue-900/20" : "text-slate-400 hover:text-white"
          )}
        >
          <LayoutDashboard className="w-4 h-4" /> 策略大厅
        </button>
        <button 
          onClick={() => setView('console')}
          className={cn(
            "px-6 py-2 rounded-xl text-xs font-bold transition-all flex items-center gap-2",
            view === 'console' ? "bg-blue-600 text-white shadow-lg shadow-blue-900/20" : "text-slate-400 hover:text-white"
          )}
        >
          <Activity className="w-4 h-4" /> 仿真控制台
        </button>
        <button 
          onClick={() => setView('dashboard')}
          className={cn(
            "px-6 py-2 rounded-xl text-xs font-bold transition-all flex items-center gap-2",
            view === 'dashboard' ? "bg-blue-600 text-white shadow-lg shadow-blue-900/20" : "text-slate-400 hover:text-white"
          )}
        >
          <PieChart className="w-4 h-4" /> 绩效仪表盘
        </button>
        <button 
          onClick={() => setView('compare')}
          className={cn(
            "px-6 py-2 rounded-xl text-xs font-bold transition-all flex items-center gap-2",
            view === 'compare' ? "bg-fuchsia-600 text-white shadow-lg shadow-fuchsia-900/20" : "text-slate-400 hover:text-white"
          )}
        >
          <GitCompare className="w-4 h-4" /> 策略 PK
        </button>
        <button 
          onClick={() => setView('factorLab')}
          className={cn(
            "px-6 py-2 rounded-xl text-xs font-bold transition-all flex items-center gap-2",
            view === 'factorLab' ? "bg-cyan-600 text-white shadow-lg shadow-cyan-900/20" : "text-slate-400 hover:text-white"
          )}
        >
          <BarChart3 className="w-4 h-4" /> 策略体检
        </button>
        <button 
          onClick={() => setView('virtualTrade')}
          className={cn(
            "px-6 py-2 rounded-xl text-xs font-bold transition-all flex items-center gap-2",
            view === 'virtualTrade' ? "bg-blue-600 text-white shadow-lg shadow-blue-900/20" : "text-slate-400 hover:text-white"
          )}
        >
          <Play className="w-4 h-4" /> 实盘模拟
        </button>
      </nav>
    </header>
  );
}
