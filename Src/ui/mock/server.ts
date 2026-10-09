// 모의 서버: 엔진(FastAPI) 없이 화면을 개발하기 위해 WebSocket 메시지를 흉내 낸다.
// 실서버와 같은 주소(ws://localhost:8000/ws)를 쓰므로, 실서버가 생기면 이 서버만 끄면 된다.
//
// 실행: npm run mock
// 옵션: MOCK_PORT=8000  MOCK_TICK_MS=1500

import { readFileSync } from 'node:fs'
import { WebSocketServer, type WebSocket } from 'ws'
import { parseCueCsv } from '../src/cues.ts'
import type { ClientMessage, DeviationType, ServerMessage } from '../src/protocol.ts'

const PORT = Number(process.env.MOCK_PORT ?? 8000)
const TICK_MS = Number(process.env.MOCK_TICK_MS ?? 1500)

const cues = parseCueCsv(readFileSync(new URL('./sample_cues.csv', import.meta.url), 'utf8'))
console.log(`[mock] 샘플 큐 ${cues.length}개 (#${cues[0].id} ~ #${cues[cues.length - 1].id})`)

// ── 시나리오 ─────────────────────────────────────────────
// 한 단계 = 한 틱(TICK_MS). sample_cues.csv 기준으로
// 정상 진행 → 애드리브 → 누락 → 노래 구간 → 반복 → 입력 끊김 → 정상 진행 순서로 흘러간다.

type Step =
  | { kind: 'say'; cue: number; confidence?: number } // 대본대로 말함
  | { kind: 'deviate'; deviation: DeviationType; cue: number } // 이탈 시작 (cue = 마지막으로 맞았던 큐)
  | { kind: 'unmatched'; cue: number } // 이탈 중 (낮은 신뢰도)
  | { kind: 'return'; cue: number } // 대본으로 돌아옴
  | { kind: 'song' } // 노래 구간: 추적을 멈춘다
  | { kind: 'silence' } // 입력 없음

const range = (from: number, to: number): Step[] =>
  Array.from({ length: to - from + 1 }, (_, i) => ({ kind: 'say', cue: from + i }))

const SCENARIO: Step[] = [
  ...range(103, 108),
  // 애드리브: 108 뒤에 대본에 없는 말 → 109로 복귀
  { kind: 'deviate', deviation: 'adlib', cue: 108 },
  { kind: 'unmatched', cue: 108 },
  { kind: 'unmatched', cue: 108 },
  { kind: 'return', cue: 109 },
  ...range(111, 112),
  // 누락: 113을 건너뛰고 114로
  { kind: 'deviate', deviation: 'skip', cue: 112 },
  { kind: 'return', cue: 114 },
  // 노래 구간 115~118: 추적을 멈춘다
  { kind: 'song' },
  { kind: 'song' },
  { kind: 'song' },
  { kind: 'song' },
  ...range(119, 122),
  // 반복: 122 뒤에 121을 다시 말함
  { kind: 'deviate', deviation: 'repeat', cue: 122 },
  { kind: 'return', cue: 121 },
  { kind: 'say', cue: 122 },
  { kind: 'say', cue: 123 },
  // 입력 끊김
  { kind: 'silence' },
  { kind: 'silence' },
  { kind: 'silence' },
  ...range(124, 128),
]

// ── 회차 실행 ────────────────────────────────────────────

const cueText = new Map(cues.map((c) => [c.id, c.text]))

/** 이탈 중 인식 글자로 보낼, 대본에 없는 말 */
const OFF_SCRIPT_LINES = [
  '아 오늘 비 진짜 많이 오네 여러분 우산 챙기셨어요',
  '근데 이 차 너무 뜨거운데',
  '잠깐만 내가 무슨 말 하려고 했지',
  '다시 다시 그러니까',
]

const jitter = (base: number, spread: number) => base + (Math.random() * 2 - 1) * spread
const round2 = (n: number) => Math.round(n * 100) / 100

class Session {
  private step = 0
  private timer: ReturnType<typeof setInterval> | undefined
  private deviation: { type: DeviationType; since: number } | null = null
  private offScriptCount = 0
  private ws: WebSocket
  showId: string

  constructor(ws: WebSocket, showId: string) {
    this.ws = ws
    this.showId = showId
  }

  start() {
    this.timer = setInterval(() => this.tick(), TICK_MS)
    this.tick()
  }

  stop() {
    clearInterval(this.timer)
  }

  private send(msg: ServerMessage) {
    this.ws.send(JSON.stringify(msg))
  }

  private position(cue: number, confidence = jitter(0.88, 0.07), transcript = cueText.get(cue) ?? '') {
    this.send({
      type: 'position.update',
      cue_id: cue,
      confidence: round2(confidence),
      latency_ms: Math.round(jitter(1200, 400)),
      transcript,
    })
  }

  private offScript() {
    return OFF_SCRIPT_LINES[this.offScriptCount++ % OFF_SCRIPT_LINES.length]
  }

  private tick() {
    const step = SCENARIO[this.step]
    if (!step) {
      console.log(`[mock] ${this.showId}: 시나리오 끝`)
      this.stop()
      return
    }
    this.step++

    // 음량 막대용으로 입력 상태는 매 틱 보낸다
    const silent = step.kind === 'silence'
    this.send({
      type: 'input.status',
      audio_level: silent ? 0 : round2(jitter(step.kind === 'song' ? 0.75 : 0.55, 0.15)),
      segment: step.kind === 'song' ? 'song' : 'dialogue',
    })

    switch (step.kind) {
      case 'say':
        this.position(step.cue, step.confidence)
        break
      case 'deviate':
        this.deviation = { type: step.deviation, since: Date.now() }
        this.position(step.cue, jitter(0.35, 0.1), this.offScript())
        this.send({
          type: 'deviation.alert',
          deviation_type: step.deviation,
          since: this.deviation.since,
          return_cue_id: null,
        })
        break
      case 'unmatched':
        this.position(step.cue, jitter(0.3, 0.1), this.offScript())
        break
      case 'return':
        if (this.deviation) {
          this.send({
            type: 'deviation.alert',
            deviation_type: this.deviation.type,
            since: this.deviation.since,
            return_cue_id: step.cue,
          })
          this.deviation = null
        }
        this.position(step.cue)
        break
      case 'song':
      case 'silence':
        break
    }
  }
}

// ── 서버 ─────────────────────────────────────────────────

const wss = new WebSocketServer({ port: PORT, path: '/ws' })

wss.on('connection', (ws) => {
  console.log('[mock] 화면 연결됨')
  let session: Session | null = null

  ws.on('message', (data) => {
    let msg: ClientMessage
    try {
      msg = JSON.parse(String(data))
    } catch {
      console.warn('[mock] JSON이 아닌 메시지 무시:', String(data))
      return
    }
    console.log('[mock] 받음:', msg)

    switch (msg.type) {
      case 'session.start':
        session?.stop()
        session = new Session(ws, msg.show_id)
        session.start()
        break
      case 'session.end':
        session?.stop()
        session = null
        break
      case 'settings.update':
        // 모의 서버는 기록만 한다. 실제 알림 보류는 엔진(⑤ 이탈 감지)이 처리.
        break
      default:
        console.warn('[mock] 모르는 메시지:', msg)
    }
  })

  ws.on('close', () => {
    session?.stop()
    console.log('[mock] 화면 연결 끊김')
  })
})

console.log(`[mock] ws://localhost:${PORT}/ws 대기 중 (틱 ${TICK_MS}ms)`)
