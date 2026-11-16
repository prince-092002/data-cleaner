import type { ReactNode } from 'react'
import { useFocusOnMount } from '@/lib/useFocusOnMount'

/** An error message that takes keyboard focus when it appears. */
export function FocusedAlert({ className, children }: { className: string; children: ReactNode }) {
  const ref = useFocusOnMount<HTMLParagraphElement>()
  return (
    <p ref={ref} tabIndex={-1} role="alert" className={`${className} outline-none`}>
      {children}
    </p>
  )
}
