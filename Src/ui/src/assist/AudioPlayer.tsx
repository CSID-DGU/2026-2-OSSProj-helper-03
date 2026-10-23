// 녹음 같이 듣기 (음성 파일 회차). 엔진이 재생하는 녹음을 화면에서도 틀어, 소리를 들으면서 자막을 볼 수 있게 한다.
// 엔진이 1초마다 보내는 재생 위치(input.status 의 audio_sec)에 맞춰 틀고, 어긋나면 그 위치로 옮긴다.
// 시연 영상 · 성능 확인용. 엔진 쪽 재생과는 별개라 여기서 소리를 꺼도 추적에는 영향이 없다.

import { useEffect, useRef, useState } from 'react'
import { AUDIO_SYNC_TOLERANCE_SEC } from '../settings'
import { ENGINE_URL } from '../useEngine'

/** 엔진 HTTP 주소 (ws://localhost:8000/ws → http://localhost:8000) */
const ENGINE_HTTP = ENGINE_URL.replace(/^ws(s?):\/\//, 'http$1://').replace(/\/ws\/?$/, '')

interface Props {
  /** 회차 시작 시각. 회차마다 녹음을 새로 받게 주소에 붙인다 */
  session: number
  /** 엔진이 재생 중인 위치 (초). 아직 안 왔거나 녹음이 끝났으면 null */
  engineSec: number | null
}

export function AudioPlayer({ session, engineSec }: Props) {
  const audioRef = useRef<HTMLAudioElement>(null)
  const [volume, setVolume] = useState(0.8)
  const [muted, setMuted] = useState(false)
  /** 브라우저가 자동 재생을 막음 → 버튼을 눌러야 소리가 난다 */
  const [blocked, setBlocked] = useState(false)

  useEffect(() => {
    const audio = audioRef.current
    if (!audio) return
    audio.volume = volume
    audio.muted = muted
  }, [volume, muted])

  // 엔진 재생 위치를 따라간다. 녹음이 끝나면(위치가 안 오면) 멈춘다
  useEffect(() => {
    const audio = audioRef.current
    if (!audio) return
    if (engineSec === null) {
      audio.pause()
      return
    }
    if (Math.abs(audio.currentTime - engineSec) > AUDIO_SYNC_TOLERANCE_SEC) audio.currentTime = engineSec
    if (audio.paused && !blocked) audio.play().catch(() => setBlocked(true))
  }, [engineSec, blocked])

  const unblock = () => {
    const audio = audioRef.current
    if (!audio) return
    if (engineSec !== null) audio.currentTime = engineSec
    audio.play().then(
      () => setBlocked(false),
      () => setBlocked(true),
    )
  }

  return (
    <span className="audio-ctl" title="녹음 같이 듣기 (엔진 재생 위치에 맞춰 틂)">
      <audio ref={audioRef} src={`${ENGINE_HTTP}/session/audio?s=${session}`} preload="auto" />
      {blocked ? (
        <button className="small" onClick={unblock}>
          소리 켜기
        </button>
      ) : (
        <button className="ghost small" onClick={() => setMuted((m) => !m)} aria-label={muted ? '소리 켜기' : '소리 끄기'}>
          {muted ? '🔇' : '🔊'}
        </button>
      )}
      <input
        type="range"
        min={0}
        max={1}
        step={0.05}
        value={volume}
        onChange={(e) => setVolume(Number(e.target.value))}
        aria-label="음량"
      />
    </span>
  )
}
