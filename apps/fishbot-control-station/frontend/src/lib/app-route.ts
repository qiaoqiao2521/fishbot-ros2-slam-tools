export type AppRoute = 'workbench' | 'results' | 'regression' | 'dashboard' | 'radar' | 'simulation' | 'cooperation'

export function resolveAppRoute(pathname: string): AppRoute {
  if (pathname === '/regression') return 'regression'
  if (pathname === '/results') return 'results'
  if (pathname === '/workbench') return 'workbench'
  if (pathname === '/cooperation') return 'cooperation'
  if (pathname === '/simulation') return 'simulation'
  return pathname === '/radar' ? 'radar' : 'dashboard'
}
