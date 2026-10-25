// 모의 서버: 엔진(FastAPI) 없이 화면을 개발하기 위해 WebSocket 메시지를 흉내 낸다.
// 실서버와 같은 주소(ws://localhost:8000/ws)를 쓰므로, 실서버가 생기면 이 서버만 끄면 된다.
//
// 실행: npm run mock
// 옵션: MOCK_PORT=8000  MOCK_TICK_MS=1500
//
// session.start 의 input 에 따라
// - 'file' · 'mic' (또는 없음): 정해 둔 시나리오를 재생 (마이크는 흉내만 낸다)
// - 'text': 화면에서 보낸 test.say 글자를 대본과 비교해 위치·이탈을 보낸다 (간단한 글자 유사도. 실제 엔진과 판단은 다름)

import { readFileSync } from 'node:fs'
import { WebSocketServer, type WebSocket } from 'ws'
import { parseCueCsv } from '../src/cues.ts'
import type { Cue } from '../src/cues.ts'
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
  | { kind: 'song'; cue: number } // 노래 구간: 실제 엔진처럼 가사 큐를 따라가되 이탈 알림은 보내지 않음
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
  // 노래 구간 115~118: 가사를 따라간다 (이탈 알림 없음)
  { kind: 'song', cue: 115 },
  { kind: 'song', cue: 116 },
  { kind: 'song', cue: 117 },
  { kind: 'song', cue: 118 },
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

interface MockSession {
  stop(): void
  say?(text: string): void
  jump?(cueId: number): void
}

class Session implements MockSession {
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
        // 음악이 섞여 신뢰도는 대사보다 조금 낮게
        this.position(step.cue, jitter(0.75, 0.08))
        break
      case 'silence':
        break
    }
  }
}

// ── 대사 입력 모드 ────────────────────────────────────────
// 입력한 글자를 음성인식 결과 한 번으로 보고, 글자 두 개씩 묶은 조각(바이그램)이 얼마나 겹치는지로 대본과 비교한다.

const normalize = (text: string) => text.replace(/[^0-9a-zA-Z가-힣]/g, '').toLowerCase()

function bigrams(text: string): Map<string, number> {
  const out = new Map<string, number>()
  for (let i = 0; i < text.length - 1; i++) {
    const g = text.slice(i, i + 2)
    out.set(g, (out.get(g) ?? 0) + 1)
  }
  return out
}

/** 0~1. 1이면 같은 글자 */
function similarity(a: string, b: string): number {
  if (!a || !b) return 0
  if (a.length < 2 || b.length < 2) return a === b ? 1 : 0
  const ga = bigrams(a)
  const gb = bigrams(b)
  let common = 0
  for (const [g, n] of ga) common += Math.min(n, gb.get(g) ?? 0)
  return (2 * common) / (a.length - 1 + (b.length - 1))
}

const WINDOW_BEFORE = 3 // 수행계획서 탐색 범위 [현재-3, 현재+10]
const WINDOW_AFTER = 10
const ACCEPT_IN_WINDOW = 0.5
const ACCEPT_ANYWHERE = 0.7 // 범위 밖은 더 확실할 때만

class TextSession implements MockSession {
  private ws: WebSocket
  showId: string
  /** 대사·가사 큐만 */
  private spoken: Cue[] = cues.filter((c) => c.type === 'dialogue' || c.type === 'lyric')
  /** spoken 안에서 지금 위치. 아직 없으면 -1 */
  private cur = -1
  private deviation: { type: DeviationType; since: number } | null = null
  private lastSayAt = 0
  private timer: ReturnType<typeof setInterval> | undefined

  constructor(ws: WebSocket, showId: string) {
    this.ws = ws
    this.showId = showId
  }

  start() {
    // 실제 엔진처럼 1초마다 입력 상태를 보낸다 (화면은 5초간 메시지가 없으면 '엔진 응답 없음')
    this.timer = setInterval(() => this.heartbeat(), 1000)
    this.heartbeat()
  }

  stop() {
    clearInterval(this.timer)
  }

  private send(msg: ServerMessage) {
    this.ws.send(JSON.stringify(msg))
  }

  private segment() {
    return this.spoken[this.cur]?.type === 'lyric' ? 'song' : 'dialogue'
  }

  private heartbeat() {
    const recent = Date.now() - this.lastSayAt < 2000
    // 0이면 화면이 '입력 없음'으로 보므로 조용할 때도 작은 값을 둔다
    this.send({ type: 'input.status', audio_level: recent ? round2(jitter(0.6, 0.1)) : 0.05, segment: this.segment() })
  }

  private best(text: string, from: number, to: number) {
    let index = -1
    let score = 0
    for (let i = Math.max(0, from); i <= Math.min(this.spoken.length - 1, to); i++) {
      const sc = similarity(text, normalize(this.spoken[i].text))
      if (sc > score) {
        score = sc
        index = i
      }
    }
    return { index, score }
  }

  say(raw: string) {
    const text = normalize(raw)
    this.lastSayAt = Date.now()
    const latency = Math.round(jitter(500, 200))
    const from = this.cur < 0 ? 0 : this.cur - WINDOW_BEFORE
    const to = this.cur < 0 ? WINDOW_AFTER : this.cur + WINDOW_AFTER
    let hit = this.best(text, from, to)
    if (hit.score < ACCEPT_IN_WINDOW) {
      const anywhere = this.best(text, 0, this.spoken.length - 1)
      hit = anywhere.score >= ACCEPT_ANYWHERE ? anywhere : { index: -1, score: Math.max(hit.score, anywhere.score) }
    }

    if (hit.index < 0) {
      // 대본에 없는 말: 위치는 그대로 두고 낮은 신뢰도로 알린 뒤, 노래 구간이 아니면 애드리브 시작
      const at = this.spoken[Math.max(0, this.cur)]
      this.send({ type: 'position.update', cue_id: at.id, confidence: round2(hit.score), latency_ms: latency, transcript: raw })
      if (!this.deviation && this.segment() === 'dialogue') {
        this.deviation = { type: 'adlib', since: Date.now() }
        this.send({ type: 'deviation.alert', deviation_type: 'adlib', since: this.deviation.since, return_cue_id: null })
      }
      return
    }

    const cue = this.spoken[hit.index]
    const song = cue.type === 'lyric'
    if (this.deviation) {
      // 애드리브 뒤 대본으로 돌아옴
      this.send({ type: 'deviation.alert', deviation_type: this.deviation.type, since: this.deviation.since, return_cue_id: cue.id })
      this.deviation = null
    } else if (!song && this.cur >= 0 && hit.index > this.cur + 1) {
      // 누락·반복은 실제 엔진처럼 복귀 큐를 채운 알림 하나로 보낸다
      this.send({ type: 'deviation.alert', deviation_type: 'skip', since: Date.now(), return_cue_id: cue.id })
    } else if (!song && hit.index < this.cur) {
      this.send({ type: 'deviation.alert', deviation_type: 'repeat', since: Date.now(), return_cue_id: cue.id })
    }
    this.cur = hit.index
    this.send({ type: 'position.update', cue_id: cue.id, confidence: round2(hit.score), latency_ms: latency, transcript: raw })
    this.heartbeat()
  }

  /** 위치 맞추기: 그 큐로 옮기고 이탈 중이었으면 복귀로 알린다 (실제 엔진과 같게) */
  jump(cueId: number) {
    const index = this.spoken.findIndex((c) => c.id === cueId)
    if (index < 0) return
    this.cur = index
    if (this.deviation) {
      this.send({ type: 'deviation.alert', deviation_type: this.deviation.type, since: this.deviation.since, return_cue_id: cueId })
      this.deviation = null
    }
    this.send({ type: 'position.update', cue_id: cueId, confidence: 1, latency_ms: 0, transcript: '' })
  }
}

// ── 서버 ─────────────────────────────────────────────────

const wss = new WebSocketServer({ port: PORT, path: '/ws' })

wss.on('connection', (ws) => {
  console.log('[mock] 화면 연결됨')
  let session: MockSession | null = null

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
      case 'session.start': {
        session?.stop()
        if (msg.input === 'text') {
          const text = new TextSession(ws, msg.show_id)
          text.start()
          session = text
        } else {
          if (msg.input === 'mic') console.log('[mock] 마이크 모드는 흉내만 냄: 시나리오를 재생')
          const scenario = new Session(ws, msg.show_id)
          scenario.start()
          session = scenario
        }
        break
      }
      case 'session.end':
        session?.stop()
        session = null
        break
      case 'settings.update':
        // 모의 서버는 기록만 한다. 실제 알림 보류는 엔진(⑤ 이탈 감지)이 처리.
        break
      case 'subtitle.send':
        // 실제로는 송출 프로그램으로 가야 함 (아직 연동 없음). 모의 서버는 기록만
        console.log(`[mock] 임시 자막 송출 (${msg.source}): ${msg.text}`)
        break
      case 'position.set':
        if (session?.jump) session.jump(msg.cue_id)
        else console.log('[mock] 위치 맞추기는 대사 입력 모드에서만 흉내냄:', msg.cue_id)
        break
      case 'test.say':
        if (session?.say) session.say(msg.text)
        else console.warn('[mock] test.say 는 대사 입력 모드에서만 받음')
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
