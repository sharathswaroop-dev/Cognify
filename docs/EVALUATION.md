# Replay evaluation

Generated 2026-11-14T03:36:16. Plans built by openai/gpt-oss-120b (11), openai/gpt-oss-20b (73), qwen/qwen3.8-27b (120); memory: basic search (BM25) + Hindsight. 24 incidents on 8 held-out machines (final score) and 8 on training machines (tuning).

**Everything below is simulated: a replay of a synthetic history, not a field trial.**

## Method

Every incident is planned several ways using **only records dated before it** (the harness raises if a later record is present). A plan is a diagnosis (the repair to do) and a parts list. Plans are scored against what really happened, deterministically, without an LLM judge:

| Metric | Meaning |
| --- | --- |
| Right fix | The plan's top repair is the repair that really fixed it. A fix that came back within 30 days is not counted as the fix; the later repair is. |
| Right parts | The van would have carried every part the real fix needed. |
| Predicted first-time fix | Right fix and right parts. |
| Failed fix avoided | The plan did not recommend an attempt that really failed on that incident. |

Arms: **no memory**; **basic search** (BM25 keyword search over earlier records); **+ Verifier** (a deterministic checker that sees only raw visit records, vetoes claims the records do not support, and sends the agent back to revise). Hindsight arms run the same plans on the Hindsight bank.

## Result on held-out machines

| Arm | Right fix | Right parts | Predicted first-time fix | Failed fix avoided |
| --- | --- | --- | --- | --- |
| No memory | 0% (0/23, 95% CI 0%-14%) | 56% (13/23, 95% CI 37%-74%) | **0% (0/23, 95% CI 0%-14%)** | 100% (13/13, 95% CI 77%-100%) |
| Basic search (BM25) | 81% (17/21, 95% CI 60%-92%) | 81% (17/21, 95% CI 60%-92%) | **81% (17/21, 95% CI 60%-92%)** | 85% (11/13, 95% CI 58%-96%) |
| Basic search + Verifier | 76% (16/21, 95% CI 55%-89%) | 86% (18/21, 95% CI 65%-95%) | **76% (16/21, 95% CI 55%-89%)** | 85% (11/13, 95% CI 58%-96%) |
| Hindsight | 71% (15/21, 95% CI 50%-86%) | 76% (16/21, 95% CI 55%-89%) | **62% (13/21, 95% CI 41%-79%)** | 83% (10/12, 95% CI 55%-95%) |
| Hindsight + Verifier | 67% (14/21, 95% CI 45%-83%) | 71% (15/21, 95% CI 50%-86%) | **62% (13/21, 95% CI 41%-79%)** | 75% (9/12, 95% CI 47%-91%) |

## Tuning (training machines only)

The Verifier's parts threshold (fixes needed on comparable units) was tuned on 8 training incidents: K=1: F1 0.75, K=2: F1 0.75, K=3: F1 0.50. K=1 chosen. The held-out machines were not looked at.

On the 8 training incidents, basic search alone predicted first-time fix for 75% (6/8, 95% CI 41%-93%).

## Failures, listed honestly

- `J-1045` on M-22, No memory: it did not name the repair that really fixed it (proposed: Cleaned the condenser coil; real: Chemical descaling of condenser tubes and cooling-tower wate)
- `J-1045` on M-22, Basic search (BM25): it did not name the repair that really fixed it (proposed: conducted generic inspection of condenser fouling, refrigerant charge,; real: Chemical descaling of condenser tubes and cooling-tower wate)
- `J-1045` on M-22, Basic search + Verifier: it did not name the repair that really fixed it (proposed: Escalate to a senior technician; real: Chemical descaling of condenser tubes and cooling-tower wate)
- `J-1045` on M-22, Hindsight: it did not name the repair that really fixed it (proposed: performed remote reset; real: Chemical descaling of condenser tubes and cooling-tower wate)
- `J-1045` on M-22, Hindsight + Verifier: it did not name the repair that really fixed it (proposed: Escalate to a senior technician; real: Chemical descaling of condenser tubes and cooling-tower wate)
- `J-1020` on M-12, No memory: it did not name the repair that really fixed it (proposed: Inspect and clean drain line, replace clogged filter, check condensate; real: Flushed drain line with nitrogen, re-laid drain pipe with pr)
- `J-1020` on M-12, Basic search (BM25): it did not name the repair that really fixed it (proposed: Check drain line, clean filter, inspect condensate pump, ensure proper; real: Flushed drain line with nitrogen, re-laid drain pipe with pr)
- `J-1020` on M-12, Basic search + Verifier: it did not name the repair that really fixed it (proposed: Escalate to a senior technician; real: Flushed drain line with nitrogen, re-laid drain pipe with pr)
- `J-1020` on M-12, Hindsight: it did not name the repair that really fixed it (proposed: Check drain line, clean filter, inspect condensate pump, ensure proper; real: Flushed drain line with nitrogen, re-laid drain pipe with pr)
- `J-1020` on M-12, Hindsight + Verifier: it did not name the repair that really fixed it (proposed: Escalate to a senior technician; real: Flushed drain line with nitrogen, re-laid drain pipe with pr)
- `J-1039` on M-21, No memory: it did not name the repair that really fixed it (proposed: Performed diagnostic checks; real: Nitrogen pressure test, brazed the joint instead of flare, v)
- `J-1039` on M-21, Basic search (BM25): it did not name the repair that really fixed it (proposed: Check system for common low cooling capacity issues; real: Nitrogen pressure test, brazed the joint instead of flare, v)
- `J-1039` on M-21, Basic search + Verifier: it did not name the repair that really fixed it (proposed: Escalate to a senior technician; real: Nitrogen pressure test, brazed the joint instead of flare, v)
- `J-1039` on M-21, Hindsight: it did not name the repair that really fixed it (proposed: perform generic diagnostic checks for low cooling capacity; real: Nitrogen pressure test, brazed the joint instead of flare, v)
- `J-1039` on M-21, Hindsight + Verifier: it did not name the repair that really fixed it (proposed: Escalate to a senior technician; real: Nitrogen pressure test, brazed the joint instead of flare, v)
- `J-1040` on M-21, No memory: it did not name the repair that really fixed it (proposed: Performed generic diagnostic checks; real: Nitrogen pressure test, brazed the joint instead of flare, v)
- `J-1040` on M-21, Basic search (BM25): it did not name the repair that really fixed it (proposed: Topped up refrigerant (R22/R410A); real: Nitrogen pressure test, brazed the joint instead of flare, v)
- `J-1040` on M-21, Basic search + Verifier: it did not name the repair that really fixed it (proposed: Topped up refrigerant (R22/R410A); real: Nitrogen pressure test, brazed the joint instead of flare, v)
- `J-1040` on M-21, Hindsight: it did not name the repair that really fixed it (proposed: Topped up refrigerant (R22/R410A); real: Nitrogen pressure test, brazed the joint instead of flare, v)
- `J-1040` on M-21, Hindsight + Verifier: it did not name the repair that really fixed it (proposed: Topped up refrigerant (R22/R410A); real: Nitrogen pressure test, brazed the joint instead of flare, v)
- `J-1062` on M-31, No memory: it did not name the repair that really fixed it (proposed: Check airflow, verify fan operation, inspect filter, ensure proper duc; real: Replaced EC fan module on fan 2 and recalibrated airflow sen)
- `J-1062` on M-31, Hindsight: the LLM was unavailable for this run (excluded from the rates)
- `J-1062` on M-31, Hindsight + Verifier: the LLM was unavailable for this run (excluded from the rates)
- `J-1021` on M-12, No memory: the LLM was unavailable for this run (excluded from the rates)
- `J-0901` on M-07, No memory: it did not name the repair that really fixed it (proposed: Check refrigerant charge, filter, coil, compressor, pressure lines, an; real: Replaced compressor contactor (DK-CTR-24V))

## Caveats (read before quoting a number)

- **Small sample.** 24 held-out incidents: the intervals are wide, so read the direction, not the percentage.
- **Synthetic data.** The history is generated, with realistic mess (wrong diagnoses, parts shortages, fixes that stop working) but recurring faults repeat on purpose.
- **Single run, LLM output varies.** A different run will give different numbers.
- **LLM availability.** 7 of 211 LLM calls came back empty (rate limits); runs where that happened are excluded from the rates, never scored as wrong answers.
- **The Verifier is deterministic code, not an LLM.** It cannot be talked into approving something the records do not support, and it can be wrong when the records are thin (n < 5 is labelled a weak signal).
- **Remote fixes** are decided by rules over the alarm log and are not part of this score.
