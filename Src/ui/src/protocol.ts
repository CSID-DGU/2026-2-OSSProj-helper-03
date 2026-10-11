// 엔진(로컬 서버) ↔ 화면 WebSocket 메시지 정의.
// 기준: 수행계획서 (5) 엔진과 화면 사이 인터페이스 표.
// 필드가 바뀌면 이 파일만 고치면 되도록, 화면 코드는 여기 있는 타입만 사용한다.

/** 대본 이탈 유형: 누락(건너뜀) · 반복 · 애드리브 */
export type DeviationType = 'skip' | 'repeat' | 'adlib'

/** 입력 구간: 대사 · 노래 */
export type Segment = 'dialogue' | 'song'

// ── 화면 → 엔진 ──────────────────────────────────────────

/** 회차 시작 */
export interface SessionStart {
  type: 'session.start'
  show_id: string
  cue_file: string
}

/** 회차 종료 */
export interface SessionEnd {
  type: 'session.end'
  show_id: string
}

/** 설정 변경 */
export interface SettingsUpdate {
  type: 'settings.update'
  /** 이 일치 점수(0~1) 미만이면 알림을 띄우지 않음 */
  alert_threshold: number
}

export type ClientMessage = SessionStart | SessionEnd | SettingsUpdate

// ── 엔진 → 화면 ──────────────────────────────────────────

/** 인식 결과마다(1~2초) 추정 위치 갱신 */
export interface PositionUpdate {
  type: 'position.update'
  cue_id: number
  /** 신뢰도 0~1 */
  confidence: number
  /** 발화부터 이 메시지까지 걸린 시간 */
  latency_ms: number
  /**
   * (추가) 이번에 인식된 글자. 보조 화면 ⑤ 인식 글자(확인용)에 쓴다.
   * 수행계획서 화면 설계에는 있지만 메시지 표에는 없어서 엔진 담당과 확인 필요.
   */
  transcript?: string
}

/** 이탈 판정 시. 대본으로 돌아오면 return_cue_id가 채워져 다시 온다. */
export interface DeviationAlert {
  type: 'deviation.alert'
  deviation_type: DeviationType
  /** 이탈 시작 시각 (epoch ms) */
  since: number
  /** 복귀한 큐. 아직 이탈 중이면 null */
  return_cue_id: number | null
}

/** 입력 상태가 바뀔 때 */
export interface InputStatus {
  type: 'input.status'
  /** 음량 0~1. 0이면 입력 없음 */
  audio_level: number
  segment: Segment
}

/** (2단계, 연동 시) 송출 프로그램이 실제로 송출한 큐 */
export interface CueOnAir {
  type: 'cue.onair'
  cue_id: number
  /** 송출 시각 (epoch ms) */
  sent_at: number
}

export type ServerMessage = PositionUpdate | DeviationAlert | InputStatus | CueOnAir

const SERVER_TYPES = new Set<ServerMessage['type']>([
  'position.update',
  'deviation.alert',
  'input.status',
  'cue.onair',
])

/** 받은 문자열을 ServerMessage로 해석. 모르는 형식이면 null */
export function parseServerMessage(raw: string): ServerMessage | null {
  try {
    const msg = JSON.parse(raw)
    if (msg && typeof msg === 'object' && SERVER_TYPES.has(msg.type)) {
      return msg as ServerMessage
    }
  } catch {
    // JSON이 아니면 무시
  }
  return null
}
