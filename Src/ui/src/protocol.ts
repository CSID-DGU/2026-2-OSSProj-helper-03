// 엔진(로컬 서버) ↔ 화면 WebSocket 메시지 정의.
// 기준: 수행계획서 (5) 엔진과 화면 사이 인터페이스 표.
// 필드가 바뀌면 이 파일만 고치면 되도록, 화면 코드는 여기 있는 타입만 사용한다.

/** 대본 이탈 유형: 누락(건너뜀) · 반복 · 애드리브 */
export type DeviationType = 'skip' | 'repeat' | 'adlib'

/** 입력 구간: 대사 · 노래 */
export type Segment = 'dialogue' | 'song'

/** 소리 원천: 녹음 파일 재생 · 마이크 · 대사 입력(테스트용, 입력한 글자를 인식 결과로 씀) */
export type InputMode = 'file' | 'mic' | 'text'

// ── 화면 → 엔진 ──────────────────────────────────────────

/** 회차 시작 */
export interface SessionStart {
  type: 'session.start'
  show_id: string
  cue_file: string
  /**
   * (추가) 소리 원천. 실서버 · 모의 서버 모두 읽는다. 없으면 실서버는 .env 의 HELPER_INPUT 을 쓴다.
   * 모의 서버는 읽는다.
   */
  input?: InputMode
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

/**
 * (추가) 테스트용 대사 입력. input 이 'text' 인 회차에서, 입력한 글자를 음성인식 결과 한 번으로 보고 추적한다.
 * 실서버는 실제 추적기 · 이탈 감지로, 모의 서버는 간단한 글자 유사도로 처리한다.
 */
export interface TestSay {
  type: 'test.say'
  text: string
}

/** 임시 자막의 출처: 인식된 말을 고친 것 · 오퍼레이터가 직접 쓴 것 */
export type SubtitleSource = 'recognized' | 'manual'

/**
 * (추가) 애드리브 임시 자막 송출. 대본에 없는 말을 오퍼레이터가 확인·수정해서 내보낸다.
 * 수행계획서에서는 '애드리브 임시 자막'이 이번 학기 범위 밖(Won't)이고 보조 화면에 송출 기능이 없었으므로(R3),
 * 팀 합의가 필요하다. 실서버는 받아서 회차 기록 · 로그에만 남긴다 (실제 송출은 2단계 송출 프로그램 연동).
 */
export interface SubtitleSend {
  type: 'subtitle.send'
  text: string
  source: SubtitleSource
}

/**
 * (추가) 위치 맞추기. 오퍼레이터가 대본 줄을 누르거나 이전/다음 버튼으로 AI 추정 위치를 고친다.
 * 송출이 아니라 엔진의 추적 위치만 옮긴다. 엔진은 그 큐에서 추적 · 이탈 판단을 다시 시작한다.
 */
export interface PositionSet {
  type: 'position.set'
  cue_id: number
}

export type ClientMessage = SessionStart | SessionEnd | SettingsUpdate | TestSay | SubtitleSend | PositionSet

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
  /**
   * (추가) 녹음 재생 회차에서 엔진이 재생 중인 위치(초). 화면이 같은 녹음(GET /session/audio)을
   * 이 위치에 맞춰 틀어, 소리를 들으면서 자막을 볼 수 있게 한다. 녹음 재생이 아니면 없음.
   */
  audio_sec?: number
}

/** (2단계, 연동 시) 송출 프로그램이 실제로 송출한 큐 */
export interface CueOnAir {
  type: 'cue.onair'
  cue_id: number
  /** 송출 시각 (epoch ms) */
  sent_at: number
}

/**
 * (추가) 엔진 오류. 회차를 못 열었거나(키 없음 · 큐/녹음 파일 없음 · 마이크 오류) 음성인식이 계속 실패할 때.
 * 화면 위에 띄워서 오퍼레이터가 원인을 바로 알게 한다.
 */
export interface EngineError {
  type: 'engine.error'
  message: string
  /** session.start: 회차를 못 엶 / recognize: 음성인식이 연달아 실패하거나 끊김 */
  during: 'session.start' | 'recognize'
}

export type ServerMessage = PositionUpdate | DeviationAlert | InputStatus | CueOnAir | EngineError

const SERVER_TYPES = new Set<ServerMessage['type']>([
  'position.update',
  'deviation.alert',
  'input.status',
  'cue.onair',
  'engine.error',
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
