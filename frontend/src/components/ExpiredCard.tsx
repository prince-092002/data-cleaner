import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { useFocusOnMount } from '@/lib/useFocusOnMount'
import { expiredMessage } from '@/lib/jobErrors'
import { useAppState } from '@/state/AppState'

/** Shown when the server no longer knows the dataset or job (on the server it is deleted after 24 hours; in the browser it is gone when the tab reloads). */
export function ExpiredCard() {
  const { dispatch } = useAppState()
  const msg = useFocusOnMount<HTMLParagraphElement>()
  return (
    <Card>
      <CardContent className="space-y-4 pt-6">
        <p ref={msg} tabIndex={-1} role="alert" className="text-red-700 outline-none">
          {expiredMessage()}
        </p>
        <Button onClick={() => dispatch({ type: 'reset' })}>Upload another file</Button>
      </CardContent>
    </Card>
  )
}
