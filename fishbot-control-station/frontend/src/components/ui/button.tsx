import * as React from 'react'
import { Slot } from '@radix-ui/react-slot'
import { cva, type VariantProps } from 'class-variance-authority'

import { cn } from '@/lib/cn'

const buttonVariants = cva(
  'inline-flex items-center justify-center whitespace-nowrap rounded-[18px] text-sm font-semibold uppercase tracking-[0.16em] transition-[transform,background-color,border-color,color,box-shadow] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:pointer-events-none disabled:opacity-50 active:scale-[0.985]',
  {
    variants: {
      variant: {
        default:
          'border border-[hsl(var(--primary))] bg-primary text-primary-foreground shadow-[0_14px_28px_rgba(61,45,19,0.18)] hover:bg-primary/92',
        secondary:
          'border border-border bg-secondary text-secondary-foreground shadow-[inset_0_1px_0_rgba(255,255,255,0.6)] hover:bg-secondary/86',
        ghost:
          'border border-transparent bg-transparent text-foreground hover:border-border hover:bg-[rgba(107,80,42,0.08)]',
        outline:
          'border border-border bg-[rgba(255,249,237,0.68)] text-foreground shadow-[inset_0_1px_0_rgba(255,255,255,0.75)] hover:bg-[rgba(238,227,204,0.86)]',
        emergency:
          'border border-red-700/35 bg-[linear-gradient(180deg,rgba(173,48,35,0.96),rgba(126,33,27,0.98))] text-white shadow-[0_16px_34px_rgba(112,31,25,0.24)] hover:bg-[linear-gradient(180deg,rgba(186,55,40,0.96),rgba(137,37,30,0.98))]',
      },
      size: {
        default: 'h-11 px-4 py-2',
        sm: 'h-9 rounded-[14px] px-3 text-xs',
        lg: 'h-12 rounded-[20px] px-6 text-sm',
        icon: 'h-11 w-11',
      },
    },
    defaultVariants: {
      variant: 'default',
      size: 'default',
    },
  },
)

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : 'button'
    return <Comp className={cn(buttonVariants({ variant, size, className }))} ref={ref} {...props} />
  },
)
Button.displayName = 'Button'

export { Button }
