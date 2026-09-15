import type { HTMLAttributes } from 'react'

import { cva, type VariantProps } from 'class-variance-authority'

import { cn } from '@/lib/cn'

const badgeVariants = cva(
  'inline-flex items-center rounded-full border px-3 py-1 text-[10px] font-semibold uppercase tracking-[0.2em]',
  {
    variants: {
      variant: {
        neutral: 'border-border bg-[rgba(255,248,235,0.72)] text-foreground/76',
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
