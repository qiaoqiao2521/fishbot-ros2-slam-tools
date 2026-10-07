export type AppRoute = 'dashboard' | 'radar' | 'simulation'

export function resolveAppRoute(pathname: string): AppRoute {
  if (pathname === '/simulation') return 'simulation'
  return pathname === '/radar' ? 'radar' : 'dashboard'
}
