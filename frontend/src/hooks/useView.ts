import { useCallback, useEffect, useState } from 'react';

export const views = ['mall', 'console', 'dashboard', 'compare', 'factorLab', 'virtualTrade', 'dailyReport', 'overnight', 'tasks'] as const;
export type AppView = typeof views[number];

export function readView(): AppView {
  const value = window.location.hash.slice(1).split('?')[0];
  return views.includes(value as AppView) ? value as AppView : 'mall';
}

export function useView() {
  const [view, update] = useState<AppView>(readView);
  useEffect(() => {
    const changed = () => update(readView());
    window.addEventListener('hashchange', changed);
    return () => window.removeEventListener('hashchange', changed);
  }, []);
  const setView = useCallback((value: AppView) => {
    window.location.hash = value;
    update(value);
  }, []);
  return [view, setView] as const;
}
