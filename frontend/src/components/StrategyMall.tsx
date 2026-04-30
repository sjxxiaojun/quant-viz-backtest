import React from 'react';
import { ChevronRight } from 'lucide-react';
import { cn } from '../utils';
import { strategyInfo, colorMap } from '../config/strategies';

interface StrategyMallProps {
  onRun: (factor: string) => void;
}

export function StrategyMall({ onRun }: StrategyMallProps) {
  return (
    <div className="space-y-12 animate-in fade-in duration-500">
      
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-8">
        {Object.entries(strategyInfo).map(([key, info]) => (
          <div 
            key={key} 
            className="group relative rounded-[2.5rem] p-8 hover:border-blue-500/30 transition-all duration-500 shadow-2xl overflow-hidden"
            style={{ background: 'rgba(13, 27, 50, 0.4)', borderWidth: '1px', borderStyle: 'solid', borderColor: 'rgba(59, 130, 246, 0.08)' }}
          >
            <div className={cn(
              "absolute -right-12 -top-12 w-48 h-48 rounded-full blur-3xl opacity-10 group-hover:opacity-30 transition-opacity duration-500 transform-gpu",
              colorMap[info.color]?.bgBlur || 'bg-blue-500'
            )} />
            
            <div className="relative z-10 space-y-6">
              <div className="flex justify-between items-start">
                <div className={cn("p-4 rounded-2xl", colorMap[info.color]?.textBg || 'bg-blue-500/10', colorMap[info.color]?.text || 'text-blue-400')}>
                  {React.createElement(info.icon, { className: "w-8 h-8" })}
                </div>
                <span className="text-[10px] font-black text-slate-500 uppercase tracking-widest px-3 py-1 rounded-full" style={{ background: 'rgba(10, 22, 40, 0.6)', borderWidth: '1px', borderStyle: 'solid', borderColor: 'rgba(59, 130, 246, 0.1)' }}>
                  {info.category}
                </span>
              </div>
              
              <div className="space-y-2">
                <h3 className="text-xl font-black text-slate-100 group-hover:text-blue-400 transition-colors">{info.name}</h3>
                <p className="text-sm text-slate-400 leading-relaxed min-h-[4.5rem]">
                  {info.desc}
                </p>
              </div>

              <div className="flex flex-wrap gap-2">
                {info.tags.map(tag => (
                  <span key={tag} className="text-[9px] font-bold text-slate-500 border border-slate-700/50 px-2 py-1 rounded-md uppercase tracking-wider">
                    #{tag}
                  </span>
                ))}
              </div>

              <button 
                onClick={() => onRun(key)}
                className="w-full hover:bg-blue-600 text-white font-bold py-4 rounded-2xl hover:border-blue-500 transition-all flex items-center justify-center gap-2 group/btn"
                style={{ background: 'rgba(10, 22, 40, 0.7)', borderWidth: '1px', borderStyle: 'solid', borderColor: 'rgba(59, 130, 246, 0.1)' }}
              >
                <span>运行仿真</span>
                <ChevronRight className="w-4 h-4 group-hover/btn:translate-x-1 transition-transform" />
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
