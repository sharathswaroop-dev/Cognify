# Replay evaluation

Generated 2026-11-07T07:33:31. Plans built by qwen/qwen3.8-27b (87), openai/gpt-oss-20b (11), openai/gpt-oss-120b (6); memory: basic search (BM25). 24 incidents on 8 held-out machines (final score) and 8 on training machines (tuning).

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
| No memory | 0% (0/13, 95% CI 0%-23%) | 62% (8/13, 95% CI 36%-82%) | **0% (0/13, 95% CI 0%-23%)** | 100% (7/7, 95% CI 65%-100%) |
| Basic search (BM25) | 64% (7/11, 95% CI 35%-85%) | 82% (9/11, 95% CI 52%-95%) | **64% (7/11, 95% CI 35%-85%)** | 100% (6/6, 95% CI 61%-100%) |
| Basic search + Verifier | 64% (7/11, 95% CI 35%-85%) | 64% (7/11, 95% CI 35%-85%) | **64% (7/11, 95% CI 35%-85%)** | 100% (6/6, 95% CI 61%-100%) |
| Hindsight (+ Verifier) | not run | not run | not run | not run |

**Not run:** Hindsight: Hindsight was not used for this run. The rows above are the arms that could be run honestly; they are not a Hindsight result.

## Tuning (training machines only)

The Verifier's parts threshold (fixes needed on comparable units) was tuned on 8 training incidents: K=1: F1 0.67, K=2: F1 0.67, K=3: F1 0.33. K=1 chosen. The held-out machines were not looked at.

On the 8 training incidents, basic search alone predicted first-time fix for 50% (3/6, 95% CI 19%-81%).

## Failures, listed honestly

- `J-1045` on M-22, No memory: it did not name the repair that really fixed it (proposed: Performed generic checks; real: Chemical descaling of condenser tubes and cooling-tower wate)
- `J-1045` on M-22, Basic search (BM25): it did not name the repair that really fixed it (proposed: Performed generic checks for condenser water flow and refrigerant char; real: Chemical descaling of condenser tubes and cooling-tower wate)
- `J-1045` on M-22, Basic search + Verifier: it did not name the repair that really fixed it (proposed: Escalate to a senior technician; real: Chemical descaling of condenser tubes and cooling-tower wate)
- `J-1020` on M-12, No memory: it did not name the repair that really fixed it (proposed: Check drain line, condensate pump, and drain pan for clogs; inspect wa; real: Flushed drain line with nitrogen, re-laid drain pipe with pr)
- `J-1020` on M-12, Basic search (BM25): it did not name the repair that really fixed it (proposed: Cleared the condensate drain line; real: Flushed drain line with nitrogen, re-laid drain pipe with pr)
- `J-1020` on M-12, Basic search + Verifier: it did not name the repair that really fixed it (proposed: Escalate to a senior technician; real: Flushed drain line with nitrogen, re-laid drain pipe with pr)
- `J-1039` on M-21, No memory: it did not name the repair that really fixed it (proposed: Performed generic checks; real: Nitrogen pressure test, brazed the joint instead of flare, v)
- `J-1039` on M-21, Basic search (BM25): it did not name the repair that really fixed it (proposed: Performed generic checks including refrigerant pressure, filter cleani; real: Nitrogen pressure test, brazed the joint instead of flare, v)
- `J-1039` on M-21, Basic search + Verifier: it did not name the repair that really fixed it (proposed: Escalate to a senior technician; real: Nitrogen pressure test, brazed the joint instead of flare, v)
- `J-1040` on M-21, No memory: it did not name the repair that really fixed it (proposed: Check system for common low cooling capacity issues; real: Nitrogen pressure test, brazed the joint instead of flare, v)
- `J-1040` on M-21, Basic search (BM25): it did not name the repair that really fixed it (proposed: Topped up refrigerant; real: Nitrogen pressure test, brazed the joint instead of flare, v)
- `J-1040` on M-21, Basic search + Verifier: it did not name the repair that really fixed it (proposed: Topped up refrigerant; real: Nitrogen pressure test, brazed the joint instead of flare, v)
- `J-1062` on M-31, No memory: it did not name the repair that really fixed it (proposed: Cleaned or replaced the filter; real: Replaced EC fan module on fan 2 and recalibrated airflow sen)
- `J-1021` on M-12, No memory: it did not name the repair that really fixed it (proposed: Cleared the condensate drain line; real: Flushed drain line with nitrogen, re-laid drain pipe with pr)
- `J-0901` on M-07, No memory: it did not name the repair that really fixed it (proposed: Conducted generic checks for high-pressure trip; real: Replaced compressor contactor (DK-CTR-24V))
- `J-1064` on M-31, No memory: it did not name the repair that really fixed it (proposed: Conducted generic checks for airflow, filter condition, and thermostat; real: Replaced EC fan module on fan 2 and recalibrated airflow sen)
- `J-1050` on M-23, No memory: it did not name the repair that really fixed it (proposed: Rebalanced the fan and secured the impeller; real: Replaced both blower bearings and realigned pulley.)
- `J-1047` on M-22, No memory: it did not name the repair that really fixed it (proposed: performed generic checks; real: Chemical descaling of condenser tubes and cooling-tower wate)
- `J-1047` on M-22, Basic search (BM25): the LLM was unavailable for this run (excluded from the rates)
- `J-1047` on M-22, Basic search + Verifier: the LLM was unavailable for this run (excluded from the rates)
- `J-1052` on M-23, No memory: it did not name the repair that really fixed it (proposed: Rebalanced the fan rotor; real: Replaced both blower bearings and realigned pulley.)
- `J-1023` on M-12, No memory: it did not name the repair that really fixed it (proposed: Cleared the condensate drain line; real: Flushed drain line with nitrogen, re-laid drain pipe with pr)
- `J-1065` on M-31, No memory: it did not name the repair that really fixed it (proposed: Performed generic checks on fan motor, power supply, and control board; real: Replaced EC fan module on fan 2 and recalibrated airflow sen)
- `J-1065` on M-31, Basic search (BM25): the LLM was unavailable for this run (excluded from the rates)
- `J-1065` on M-31, Basic search + Verifier: the LLM was unavailable for this run (excluded from the rates)

## Caveats (read before quoting a number)

- **Small sample.** 24 held-out incidents: the intervals are wide, so read the direction, not the percentage.
- **Synthetic data.** The history is generated, with realistic mess (wrong diagnoses, parts shortages, fixes that stop working) but recurring faults repeat on purpose.
- **Single run, LLM output varies.** A different run will give different numbers.
- **LLM availability.** 94 of 179 LLM calls came back empty (rate limits); runs where that happened are excluded from the rates, never scored as wrong answers.
- **The Verifier is deterministic code, not an LLM.** It cannot be talked into approving something the records do not support, and it can be wrong when the records are thin (n < 5 is labelled a weak signal).
- **Remote fixes** are decided by rules over the alarm log and are not part of this score.
