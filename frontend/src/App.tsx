import { Stepper } from '@/components/Stepper'
import { UploadScreen } from '@/screens/UploadScreen'
import { ProfileScreen } from '@/screens/ProfileScreen'
import { FixesScreen } from '@/screens/FixesScreen'
import { ProcessingScreen } from '@/screens/ProcessingScreen'
import { ResultsScreen } from '@/screens/ResultsScreen'
import { DownloadsScreen } from '@/screens/DownloadsScreen'
import { RestoreGate } from '@/screens/RestoreGate'
import { AppStateProvider, useAppState } from '@/state/AppState'

function Shell() {
  const { state } = useAppState()
  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:rounded focus:bg-white focus:px-3 focus:py-2"
      >
        Skip to content
      </a>
      <header className="border-b bg-white">
        <div className="mx-auto flex max-w-5xl flex-col gap-4 px-4 py-4">
          <p className="text-lg font-semibold">Data Cleaner</p>
          <Stepper />
        </div>
      </header>
      <main id="main" className="mx-auto max-w-5xl px-4 py-6">
        <RestoreGate>
          {state.step === 0 ? (
            <UploadScreen />
          ) : state.step === 1 ? (
            <ProfileScreen />
          ) : state.step === 2 ? (
            <FixesScreen />
          ) : state.step === 3 ? (
            <ProcessingScreen />
          ) : state.step === 4 ? (
            <ResultsScreen />
          ) : (
            <DownloadsScreen />
          )}
        </RestoreGate>
      </main>
    </div>
  )
}

export default function App() {
  return (
    <AppStateProvider>
      <Shell />
    </AppStateProvider>
  )
}
