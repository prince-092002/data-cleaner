import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { EXPIRED_MESSAGE } from '@/lib/jobErrors'
import { useAppState } from '@/state/AppState'

/** Shown when the server no longer knows the dataset or job (it is deleted after 24 hours). */
export function ExpiredCard() {
  const { dispatch } = useAppState()
  return (
    <Card>
      <CardContent className="space-y-4 pt-6">
        <p role="alert" className="text-red-700">
          {EXPIRED_MESSAGE}
        </p>
        <Button onClick={() => dispatch({ type: 'reset' })}>Upload another file</Button>
      </CardContent>
    </Card>
  )
}
