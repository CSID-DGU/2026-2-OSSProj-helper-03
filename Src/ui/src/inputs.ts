// 시작 화면에서 고르는 소리 입력. 엔진에는 browser-mic · browser-file 둘 다 'browser'로 간다
// (소리는 화면이 바이너리로 보냄, browserAudio.ts).

import type { InputMode } from './protocol'

export type InputChoice = 'file' | 'mic' | 'text' | 'browser-mic' | 'browser-file'

export const INPUT_OPTIONS: { choice: InputChoice; label: string; hint: string }[] = [
  { choice: 'file', label: '음성 파일', hint: '서버(엔진을 켠 컴퓨터)에 있는 녹음을 실제 시간 속도로 재생하며 추적' },
  { choice: 'mic', label: '마이크', hint: '서버(엔진을 켠 컴퓨터)에 꽂힌 마이크 소리를 추적' },
  { choice: 'text', label: '대사 입력 (테스트)', hint: '대사를 직접 입력하면 인식 결과로 보고 추적. 녹음·마이크 없이 확인용' },
  { choice: 'browser-mic', label: '내 마이크', hint: '지금 이 브라우저의 마이크 소리를 엔진으로 보내 추적. 처음에 마이크 사용을 허락해야 함' },
  {
    choice: 'browser-file',
    label: '내 녹음 파일',
    hint: '고른 녹음 파일을 이 브라우저에서 틀면서 그 소리를 엔진으로 보내 추적. 파일은 서버에 저장되지 않음',
  },
]

export const INPUT_LABEL: Record<InputChoice, string> = Object.fromEntries(
  INPUT_OPTIONS.map((o) => [o.choice, o.label]),
) as Record<InputChoice, string>

/** 화면에 보일 소리 입력. 인터넷 서버용으로 빌드할 때 VITE_INPUTS(쉼표로 나열)로 줄인다. 비우면 전부 */
export const AVAILABLE_INPUTS: InputChoice[] = (() => {
  const raw: string | undefined = import.meta.env.VITE_INPUTS
  const all = INPUT_OPTIONS.map((o) => o.choice)
  if (!raw) return all
  const picked = raw.split(',').map((s) => s.trim()).filter((s): s is InputChoice => all.includes(s as InputChoice))
  return picked.length > 0 ? picked : all
})()

export const isBrowserInput = (c: InputChoice) => c === 'browser-mic' || c === 'browser-file'

/** 엔진에 보낼 소리 입력 */
export const wireInput = (c: InputChoice): InputMode => (isBrowserInput(c) ? 'browser' : (c as InputMode))
