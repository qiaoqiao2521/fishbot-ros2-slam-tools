import type { HTMLAttributes } from 'react'

import { cva, type VariantProps } from 'class-variance-authority'

import { cn } from '@/lib/cn'

const badgeVariants = cva(
  'inline-flex items-center rounded-md border px-2 py-0.5 text-[11px] font-medium',
  {
    variants: {
      variant: {
        neutral: 'border-border bg-slate-50 text-slate-600',
        success: 'border-emerald-800/20 bg-emerald-800/10 text-emerald-900',
        warning: 'border-amber-800/20 bg-amber-700/10 text-amber-900',
        danger: 'border-red-800/20 bg-red-700/10 text-red-900',
      },
    },
    defaultVariants: {
      variant: 'neutral',
    },
  },
)

type BadgeProps = HTMLAttributes<HTMLDivElement> & VariantProps<typeof badgeVariants>

export function Badge({ className, variant, ...props }: BadgeProps) {
  return <div className={cn(badgeVariants({ variant }), className)} {...props} />
}
