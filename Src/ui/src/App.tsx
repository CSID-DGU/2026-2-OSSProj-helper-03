import { useEffect, useRef, useState } from 'react'
import { AssistScreen } from './assist/AssistScreen'
import { captureErrorMessage, startCapture, type Capture } from './browserAudio'
import type { Cue } from './cues'
import { isBrowserInput, wireInput, type InputChoice } from './inputs'
import { DEFAULT_ALERT_THRESHOLD } from './settings'
import { StartPanel, type StartRequest } from './StartPanel'
import { engineUrl, useEngine } from './useEngine'

interface Show {
  name: string
  cueFile: string
  cues: Cue[]
  input: InputChoice
  /** 회차 시작 시각 (epoch ms). 경과 시간 표시용 */
  startedAt: number
}

const CODE_KEY = 'helper.code'

/** 접속 코드: 주소의 ?code= 가 먼저, 없으면 지난번에 쓴 코드 */
function initialCode(): string {
  const fromUrl = new URLSearchParams(window.location.search).get('code')
  if (fromUrl) return fromUrl
  try {
    return localStorage.getItem(CODE_KEY) ?? ''
  } catch {
    return ''
  }
}

export default function App() {
  const [code, setCode] = useState(initialCode)
  const { state, send, sendAudio, reset } = useEngine(engineUrl(code))
  const [show, setShow] = useState<Show | null>(null)
  const [startError, setStartError] = useState<string | null>(null)
  const capture = useRef<Capture | null>(null)
  /** 회차 번호. 소리 받기 준비가 끝나기 전에 회차를 끝냈으면 늦게 준비된 것을 바로 멈춘다 */
  const run = useRef(0)

  const stopCapture = () => {
    capture.current?.stop()
    capture.current = null
  }

  const changeCode = (next: string) => {
    try {
      localStorage.setItem(CODE_KEY, next)
    } catch {
      // 저장이 막혀 있어도 이번 접속에는 지장 없음
    }
    setCode(next)
  }

  const start = (req: StartRequest) => {
    reset()
    setStartError(null)
    const id = ++run.current
    const sent = send({
      type: 'session.start',
      show_id: req.name,
      cue_file: req.cueFile,
      cue_csv: req.csv,
      input: wireInput(req.input),
    })
    if (!sent) return
    setShow({ name: req.name, cueFile: req.cueFile, cues: req.cues, input: req.input, startedAt: Date.now() })
    if (isBrowserInput(req.input)) {
      const source = req.input === 'browser-file' && req.audioFile ? { kind: 'file' as const, file: req.audioFile } : { kind: 'mic' as const }
      // 버튼을 누른 그 순간에 시작해야 브라우저가 소리 재생 · 마이크를 허락한다
      startCapture(source, sendAudio)
        .then((c) => {
          if (run.current === id) capture.current = c
          else c.stop()
        })
        .catch((e) => {
          if (run.current !== id) return
          send({ type: 'session.end', show_id: req.name })
          setShow(null)
          setStartError(captureErrorMessage(e))
        })
    }
  }

  const end = () => {
    run.current++
    stopCapture()
    if (show) send({ type: 'session.end', show_id: show.name })
    setShow(null)
  }

  // 회차를 못 열었거나 시간 제한으로 멈추면 소리 보내기도 멈춘다
  const errorDuring = state.error?.during
  useEffect(() => {
    if (errorDuring === 'session.start' || errorDuring === 'limit') stopCapture()
  }, [errorDuring, state.error?.at])

  // 화면을 닫을 때
  useEffect(() => stopCapture, [])

  if (!show) {
    return (
      <StartPanel connection={state.connection} code={code} onCode={changeCode} error={startError} onStart={start} />
    )
  }

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
      onJump={(cueId) => send({ type: 'position.set', cue_id: cueId })}
      onSendCue={(cueId, groupedIds, passedIds) =>
        send({ type: 'cue.send', cue_id: cueId, grouped_ids: groupedIds, passed_ids: passedIds })
      }
    />
  )
}
