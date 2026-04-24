export type AppRoute = 'dashboard' | 'radar'

export function resolveAppRoute(pathname: string): AppRoute {
  return pathname === '/radar' ? 'radar' : 'dashboard'
}
