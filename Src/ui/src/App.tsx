import { useState } from 'react'
import { AssistScreen } from './assist/AssistScreen'
import type { Cue } from './cues'
import type { InputMode } from './protocol'
import { DEFAULT_ALERT_THRESHOLD } from './settings'
import { StartPanel } from './StartPanel'
import { useEngine } from './useEngine'

interface Show {
  name: string
  cueFile: string
  cues: Cue[]
  input: InputMode
  /** 회차 시작 시각 (epoch ms). 경과 시간 표시용 */
  startedAt: number
}

export default function App() {
  const { state, send, reset } = useEngine()
  const [show, setShow] = useState<Show | null>(null)

  const start = (next: Omit<Show, 'startedAt'>) => {
    reset()
    if (send({ type: 'session.start', show_id: next.name, cue_file: next.cueFile, input: next.input })) {
      setShow({ ...next, startedAt: Date.now() })
    }
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
      input={show.input}
      startedAt={show.startedAt}
      engine={state}
      threshold={DEFAULT_ALERT_THRESHOLD}
      onEnd={end}
      onSay={(text) => send({ type: 'test.say', text })}
      onSendSubtitle={(text, source) => send({ type: 'subtitle.send', text, source })}
    />
  )
}
