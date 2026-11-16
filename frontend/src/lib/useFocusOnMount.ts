import { useEffect, useRef } from 'react'

/** Put keyboard focus on a message when it appears (screen readers read it; focus is not lost to the page body). */
export function useFocusOnMount<T extends HTMLElement>() {
  const ref = useRef<T>(null)
  useEffect(() => {
    ref.current?.focus()
  }, [])
  return ref
}
