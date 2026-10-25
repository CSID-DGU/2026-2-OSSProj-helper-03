import { useCallback, useEffect, useReducer, useRef } from 'react'
import {
  parseServerMessage,
  type ClientMessage,
  type CueOnAir,
  type DeviationAlert,
  type DeviationType,
  type InputStatus,
  type PositionUpdate,
  type ServerMessage,
} from './protocol'

/** 엔진 주소. 실서버와 모의 서버 모두 기본값을 쓴다. .env.local의 VITE_ENGINE_URL로 바꿀 수 있다. */
export const ENGINE_URL: string = import.meta.env.VITE_ENGINE_URL ?? 'ws://localhost:8000/ws'

export type Connection = 'connecting' | 'open' | 'closed'

/** 이번 회차의 이탈 한 건. since(이탈 시작 시각)로 시작 알림과 복귀 알림을 묶는다. */
export interface DeviationLogEntry {
  since: number
  deviationType: DeviationType
  /** 아직 이탈 중이면 null */
  returnCueId: number | null
  /** 복귀 알림을 받은 시각. 아직 이탈 중이면 null */
  returnedAt: number | null
}

/** 인식 결과 한 번: AI가 고른 큐와 실제로 들린 글자. 'AI 추정 / 실제 대사' 기록에 쓴다. */
export interface RecognitionEntry {
  /** 받은 시각 (epoch ms) */
  at: number
  /** 발화 시각 추정 (받은 시각 - 처리 지연) */
  heardAt: number
  cueId: number
  confidence: number
  transcript: string
}

/** 화면에 남겨 둘 인식 결과 수 (오래된 것부터 버림) */
const RECOGNITION_LOG_MAX = 300

export interface EngineState {
  connection: Connection
  position: PositionUpdate | null
  /** 가장 최근 이탈 알림. 복귀하면 return_cue_id가 채워진 상태로 남는다. */
  deviation: DeviationAlert | null
  /** deviation을 받은 시각 (epoch ms). 복귀 알림이면 복귀 시각이 된다. */
  deviationAt: number | null
  /** 이번 회차의 이탈 기록. 오래된 것부터 */
  deviationLog: DeviationLogEntry[]
  /** 이번 회차의 인식 결과 기록. 오래된 것부터 */
  recognitionLog: RecognitionEntry[]
  input: InputStatus | null
  /** (2단계) 송출 프로그램이 마지막으로 송출한 큐 */
  onAir: CueOnAir | null
  /** 마지막으로 메시지를 받은 시각 (epoch ms) */
  lastMessageAt: number | null
}

const initialState: EngineState = {
  connection: 'connecting',
  position: null,
  deviation: null,
  deviationAt: null,
  deviationLog: [],
  recognitionLog: [],
  input: null,
  onAir: null,
  lastMessageAt: null,
}

type Action =
  | { kind: 'connection'; connection: Connection }
  | { kind: 'message'; msg: ServerMessage; at: number }
  | { kind: 'reset' }

function reducer(state: EngineState, action: Action): EngineState {
  switch (action.kind) {
    case 'connection':
      return { ...state, connection: action.connection }
    case 'reset':
      return { ...initialState, connection: state.connection }
    case 'message': {
      const { msg, at } = action
      const next = { ...state, lastMessageAt: at }
      switch (msg.type) {
        case 'position.update':
          return { ...next, position: msg, recognitionLog: logRecognition(state.recognitionLog, msg, at) }
        case 'deviation.alert':
          return { ...next, deviation: msg, deviationAt: at, deviationLog: logDeviation(state.deviationLog, msg, at) }
        case 'input.status':
          return { ...next, input: msg }
        case 'cue.onair':
          return { ...next, onAir: msg }
      }
    }
  }
}

/** 인식 글자가 있는 위치 갱신만 남긴다. 직전과 같은 큐·같은 글자면 건너뛴다. */
function logRecognition(log: RecognitionEntry[], msg: PositionUpdate, at: number): RecognitionEntry[] {
  const transcript = msg.transcript?.trim()
  if (!transcript) return log
  const last = log[log.length - 1]
  if (last && last.cueId === msg.cue_id && last.transcript === transcript) return log
  const entry: RecognitionEntry = {
    at,
    heardAt: at - msg.latency_ms,
    cueId: msg.cue_id,
    confidence: msg.confidence,
    transcript,
  }
  return [...log, entry].slice(-RECOGNITION_LOG_MAX)
}

/** 시작 알림이면 새 기록을 더하고, 복귀 알림이면 같은 since의 기록을 채운다 */
function logDeviation(log: DeviationLogEntry[], msg: DeviationAlert, at: number): DeviationLogEntry[] {
  const entry: DeviationLogEntry = {
    since: msg.since,
    deviationType: msg.deviation_type,
    returnCueId: msg.return_cue_id,
    returnedAt: msg.return_cue_id === null ? null : at,
  }
  const i = log.findIndex((e) => e.since === msg.since)
  if (i === -1) return [...log, entry]
  // 이미 복귀한 기록을 늦게 온 시작 알림이 덮어쓰지 않게 한다
  if (msg.return_cue_id === null) return log
  return log.map((e, j) => (j === i ? entry : e))
}

const RETRY_MIN_MS = 1000
const RETRY_MAX_MS = 5000

/** 엔진과 WebSocket으로 연결하고, 받은 메시지를 화면용 상태로 모은다. 끊기면 자동으로 다시 연결한다. */
export function useEngine(url: string = ENGINE_URL) {
  const [state, dispatch] = useReducer(reducer, initialState)
  const socketRef = useRef<WebSocket | null>(null)

  useEffect(() => {
    let retryMs = RETRY_MIN_MS
    let retryTimer: ReturnType<typeof setTimeout> | undefined
    let disposed = false

    const connect = () => {
      dispatch({ kind: 'connection', connection: 'connecting' })
      const ws = new WebSocket(url)
      socketRef.current = ws

      ws.onopen = () => {
        retryMs = RETRY_MIN_MS
        dispatch({ kind: 'connection', connection: 'open' })
      }
      ws.onmessage = (event) => {
        const msg = parseServerMessage(String(event.data))
        if (msg) dispatch({ kind: 'message', msg, at: Date.now() })
        else console.warn('[engine] 알 수 없는 메시지', event.data)
      }
      ws.onclose = () => {
        if (socketRef.current === ws) socketRef.current = null
        if (disposed) return
        dispatch({ kind: 'connection', connection: 'closed' })
        retryTimer = setTimeout(connect, retryMs)
        retryMs = Math.min(retryMs * 2, RETRY_MAX_MS)
      }
    }

    connect()
    return () => {
      disposed = true
      clearTimeout(retryTimer)
      socketRef.current?.close()
      socketRef.current = null
    }
  }, [url])

  /** 엔진으로 메시지 전송. 연결이 안 돼 있으면 false */
  const send = useCallback((msg: ClientMessage): boolean => {
    const ws = socketRef.current
    if (!ws || ws.readyState !== WebSocket.OPEN) return false
    ws.send(JSON.stringify(msg))
    return true
  }, [])

  /** 회차를 새로 시작할 때 이전 회차 상태를 비운다 */
  const reset = useCallback(() => dispatch({ kind: 'reset' }), [])

  return { state, send, reset }
}
