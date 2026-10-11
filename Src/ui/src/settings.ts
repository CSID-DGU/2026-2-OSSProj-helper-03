// 화면 동작 기준값. 설정 화면이 생기면 여기 기본값을 초기값으로 쓴다.

/** 신뢰도가 이 값 미만이면 현재 위치를 '불확실'로 표시한다. 엔진의 alert_threshold 기본값과 같게 둔다. */
export const DEFAULT_ALERT_THRESHOLD = 0.6

/** 복귀 큐 번호를 크게 보여 주는 시간. 이 시간이 지나면 '최근 복귀' 한 줄로 줄어든다. */
export const RETURN_HIGHLIGHT_MS = 10_000

/** 연결은 살아 있는데 이 시간 동안 메시지가 없으면 '엔진 응답 없음'으로 표시한다. */
export const STALE_MS = 5_000

/** 대본 목록을 손으로 스크롤하면 이 시간 동안 현재 위치 따라가기를 멈춘다. */
export const MANUAL_SCROLL_PAUSE_MS = 5_000
