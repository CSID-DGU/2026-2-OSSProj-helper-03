// 화면 밝기 단계 (어두운 공연장용). 누를 때마다 다음 단계로 바뀌고, 고른 값은 브라우저에 기억한다.

import { useEffect, useState } from 'react'
import { BRIGHTNESS_LEVELS } from './settings'

const STORAGE_KEY = 'helper.brightness'
const LEVELS: readonly number[] = BRIGHTNESS_LEVELS

function load(): number {
  try {
    const saved = Number(localStorage.getItem(STORAGE_KEY))
    return LEVELS.includes(saved) ? saved : LEVELS[0]
  } catch {
    return LEVELS[0]
  }
}

export function useBrightness() {
  const [level, setLevel] = useState(load)

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, String(level))
    } catch {
      // 저장이 막혀 있으면 이번 회차에만 적용
    }
  }, [level])

  const next = () => setLevel((cur) => LEVELS[(LEVELS.indexOf(cur) + 1) % LEVELS.length])

  return { level, next }
}
