const STEPS = ['رفع الفيديو', 'اختيار المتكلم', 'المعالجة', 'النتيجة'] as const;

export type StepIndex = 1 | 2 | 3 | 4;

/** Four-step progress rail. Purely navigational context, no fake completion percentages. */
export function Steps({ current }: { current: StepIndex }) {
  return (
    <ol className="steps" aria-label="مراحل العملية">
      {STEPS.map((label, index) => {
        const step = (index + 1) as StepIndex;
        const state = step < current ? 'done' : step === current ? 'current' : 'todo';
        return (
          <li
            key={label}
            className="steps__item"
            data-state={state}
            aria-current={state === 'current' ? 'step' : undefined}
          >
            <span className="steps__num">{state === 'done' ? '✓' : step}</span>
            {label}
          </li>
        );
      })}
    </ol>
  );
}
