// 화면 밝기 (어두운 공연장에서 눈부시지 않게). 버튼을 누를 때마다 100% → 75% → 50% → 100%.
// 화면 전체 위에 검은 막을 덮어 어둡게 한다 (클릭은 그대로 통과).

export function BrightnessButton({ level, onNext }: { level: number; onNext: () => void }) {
  return (
    <button className="ghost small" onClick={onNext} title="화면 밝기 (누를 때마다 바뀜)">
      밝기 {Math.round(level * 100)}%
    </button>
  )
}

export function DimLayer({ level }: { level: number }) {
  if (level >= 1) return null
  return <div className="dim" style={{ opacity: 1 - level }} aria-hidden />
}
