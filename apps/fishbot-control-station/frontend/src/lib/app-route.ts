export type AppRoute = 'workbench' | 'dashboard' | 'radar' | 'simulation' | 'cooperation'

export function resolveAppRoute(pathname: string): AppRoute {
  if (pathname === '/workbench') return 'workbench'
  if (pathname === '/cooperation') return 'cooperation'
  if (pathname === '/simulation') return 'simulation'
  return pathname === '/radar' ? 'radar' : 'dashboard'
}
