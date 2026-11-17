// 브라우저 소리 입력: 테스터의 마이크나 녹음 파일 소리를 16kHz 모노 PCM16 조각(0.1초)으로 바꿔 엔진에 보낸다.
// 엔진을 인터넷 서버에 올렸을 때 쓴다 (서버에는 마이크가 없음). 소리는 저장하지 않고 보내기만 한다.

export type BrowserSource = { kind: 'mic' } | { kind: 'file'; file: File }

/** 타입스크립트 6 의 Float32Array 는 버퍼 종류까지 따지므로 넓게 둔다 */
type Samples = Float32Array<ArrayBufferLike>

export interface Capture {
  stop: () => void
}

const TARGET_RATE = 16000
const CHUNK = TARGET_RATE / 10 // 0.1초

// 소리 처리 스레드에서 받은 조각을 그대로 화면 쪽으로 넘기는 작은 처리기 (파일을 따로 두지 않으려고 글자로 둠)
const TAP_WORKLET = `
class HelperTap extends AudioWorkletProcessor {
  process(inputs) {
    const ch = inputs[0] && inputs[0][0]
    if (ch) this.port.postMessage(ch.slice(0))
    return true
  }
}
registerProcessor('helper-tap', HelperTap)
`

/** 브라우저 주파수(보통 48kHz) → 16kHz. 출력 한 샘플마다 그 구간 입력을 평균 내서(높은 소리 줄이기) 뽑는다 */
export class Resampler {
  private buf: Samples = new Float32Array(0)
  /** 다음 출력 샘플의 위치 (buf 안, 입력 샘플 단위) */
  private t = 0
  private readonly ratio: number

  constructor(fromRate: number, toRate: number = TARGET_RATE) {
    this.ratio = fromRate / toRate
    this.t = this.ratio / 2
  }

  push(input: Samples): Samples {
    this.buf = concat(this.buf, input)
    const half = this.ratio / 2
    const out: number[] = []
    while (this.t + half <= this.buf.length) {
      const a = Math.max(0, Math.floor(this.t - half))
      const b = Math.min(this.buf.length, Math.max(a + 1, Math.ceil(this.t + half)))
      let sum = 0
      for (let i = a; i < b; i++) sum += this.buf[i]
      out.push(sum / (b - a))
      this.t += this.ratio
    }
    const drop = Math.max(0, Math.floor(this.t - half))
    if (drop > 0) {
      this.buf = this.buf.slice(drop)
      this.t -= drop
    }
    return Float32Array.from(out)
  }
}

function concat(a: Samples, b: Samples): Samples {
  if (a.length === 0) return b
  const out = new Float32Array(a.length + b.length)
  out.set(a)
  out.set(b, a.length)
  return out
}

export function toPcm16(x: Samples): ArrayBuffer {
  const out = new Int16Array(x.length)
  for (let i = 0; i < x.length; i++) {
    const v = Math.max(-1, Math.min(1, x[i]))
    out[i] = Math.round(v * 32767)
  }
  return out.buffer
}

/**
 * 소리 받기를 시작한다. send 로 0.1초마다 PCM16 조각을 넘기고, 녹음 파일이 끝나면 onEnded 를 부른다.
 * 회차 시작 버튼을 누른 그 순간에 불러야 한다 (브라우저는 사용자 동작 없이 소리를 틀지 못하게 막음).
 */
export async function startCapture(
  source: BrowserSource,
  send: (pcm: ArrayBuffer) => void,
  onEnded?: () => void,
): Promise<Capture> {
  const ctx = new AudioContext()
  let stream: MediaStream | null = null
  let player: AudioBufferSourceNode | null = null
  try {
    const url = URL.createObjectURL(new Blob([TAP_WORKLET], { type: 'application/javascript' }))
    try {
      await ctx.audioWorklet.addModule(url)
    } finally {
      URL.revokeObjectURL(url)
    }
    // 채널 1개로 받으면 스테레오도 브라우저가 모노로 섞어 준다
    const tap = new AudioWorkletNode(ctx, 'helper-tap', {
      channelCount: 1,
      channelCountMode: 'explicit',
      channelInterpretation: 'speakers',
    })
    const mute = ctx.createGain()
    mute.gain.value = 0
    tap.connect(mute).connect(ctx.destination) // 소리는 내지 않고 처리만 돌게

    const resampler = new Resampler(ctx.sampleRate)
    let pending: Samples = new Float32Array(0)
    tap.port.onmessage = (e: MessageEvent<Float32Array>) => {
      pending = concat(pending, resampler.push(e.data))
      while (pending.length >= CHUNK) {
        send(toPcm16(pending.subarray(0, CHUNK)))
        pending = pending.slice(CHUNK)
      }
    }

    if (source.kind === 'mic') {
      stream = await navigator.mediaDevices.getUserMedia({
        // 말소리를 그대로 받도록 브라우저의 소리 보정은 끈다
        audio: { channelCount: 1, echoCancellation: false, noiseSuppression: false, autoGainControl: false },
      })
      ctx.createMediaStreamSource(stream).connect(tap)
    } else {
      const decoded = await ctx.decodeAudioData(await source.file.arrayBuffer())
      player = ctx.createBufferSource()
      player.buffer = decoded
      player.connect(tap)
      player.connect(ctx.destination) // 테스터가 들으면서 화면을 볼 수 있게
      player.onended = () => onEnded?.()
      player.start()
    }
    await ctx.resume()

    return {
      stop: () => {
        tap.port.onmessage = null
        if (player) {
          player.onended = null
          try {
            player.stop()
          } catch {
            // 이미 끝남
          }
        }
        stream?.getTracks().forEach((t) => t.stop())
        void ctx.close()
      },
    }
  } catch (e) {
    stream?.getTracks().forEach((t) => t.stop())
    void ctx.close()
    throw e
  }
}

/** 사용자에게 보여 줄 오류 문구 */
export function captureErrorMessage(e: unknown): string {
  const name = e instanceof DOMException ? e.name : ''
  if (name === 'NotAllowedError') return '마이크 사용이 막혀 있습니다. 주소창 옆 자물쇠 아이콘에서 마이크를 허용해 주세요'
  if (name === 'NotFoundError') return '마이크를 찾을 수 없습니다'
  if (name === 'EncodingError') return '이 녹음 파일을 열 수 없습니다 (wav, mp3, m4a 등을 써 주세요)'
  return e instanceof Error ? e.message : String(e)
}
