export type AppRoute = 'dashboard' | 'radar' | 'simulation' | 'cooperation'

export function resolveAppRoute(pathname: string): AppRoute {
  if (pathname === '/cooperation') return 'cooperation'
  if (pathname === '/simulation') return 'simulation'
  return pathname === '/radar' ? 'radar' : 'dashboard'
}
