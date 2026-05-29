# Red-Team Review

## Summary

Plan is directionally correct: narrow audio-story MVP, no CapCut, no cinematic effects. Main risks are scope creep, schema compatibility, subtitle expectations, and Chap 1 path/performance assumptions.

## Findings

### Major

1. **Subtitle one-command expectation can become false**

The command cannot generate timed SRT from script alone without a transcription/timing model or existing transcript. Plan handles this by making transcription explicit with `--model` or allowing SRT warning. Keep this boundary in implementation. Do not silently promise SRT if no timing source exists.

2. **`media` schema migration is the riskiest phase**

Changing `StoryboardSceneSpec` can break all existing jobs if done carelessly. Phase 2 correctly requires tests-before and backward compatibility. Implementation should prefer a normalized property/helper over a broad rename.

3. **Preview mode can corrupt the real job if implemented by mutating `job.yaml`**

Preview should use a transient job/plan or workspace-only override. Phase 3 calls this out. Treat it as a hard requirement.

### Minor

4. **Cover thumbnail should not couple package to Chap folders**

Keep cover preference as explicit input from `make-youtube`; generic `package` should remain job/output-based.

5. **Gdrive mount may make real smoke flaky**

Preview smoke is useful but should not be a deterministic CI gate. Record result manually.

## Scope Pressure

Reject these during MVP:

- rain/wind effects engine
- Shorts output
- AI semantic media retrieval
- text overlay thumbnail design
- automatic model download

## Required Plan Adjustments

Already represented:

- TDD per phase.
- SRT timing caveat.
- Preview mutation risk.
- Backward-compatible schema.
- Long-form only.

## Verdict

Proceed. Plan is implementable if the team respects the MVP boundary.
