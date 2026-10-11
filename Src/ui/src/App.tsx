import { useState } from 'react'
import { AssistScreen } from './assist/AssistScreen'
import type { Cue } from './cues'
import { DEFAULT_ALERT_THRESHOLD } from './settings'
import { StartPanel } from './StartPanel'
import { useEngine } from './useEngine'

interface Show {
  name: string
  cueFile: string
  cues: Cue[]
}

export default function App() {
  const { state, send, reset } = useEngine()
  const [show, setShow] = useState<Show | null>(null)

  const start = (next: Show) => {
    reset()
    if (send({ type: 'session.start', show_id: next.name, cue_file: next.cueFile })) setShow(next)
  }

  const end = () => {
    if (show) send({ type: 'session.end', show_id: show.name })
    setShow(null)
  }

  if (!show) return <StartPanel connection={state.connection} onStart={start} />

  return (
    <AssistScreen
      showName={show.name}
      cues={show.cues}
      engine={state}
      threshold={DEFAULT_ALERT_THRESHOLD}
      onEnd={end}
    />
  )
}
