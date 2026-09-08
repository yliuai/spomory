# Epic 3.6: rule-based vs. GRPO-trained policy comparison

The first training+comparison run produced a misleading "learned
nothing" conclusion -- as you'll see below, that conclusion itself was
the product of two real bugs, not the training method or data scale. After
fixing the bugs and expanding the dataset to 140 samples and retraining,
the trained policy agreed with the rule-based baseline on 4 of 5 test
scenarios, and on the 5th (whether small talk about the weather should be
remembered) gave a different, possibly more sensible judgment. This
records the full process, not just the final good-looking numbers.

## Round one: looked like "learned nothing," but the diagnosis was wrong

Ran 3 epochs on a real GPU (2×TITAN RTX 24GB) + a real
`Qwen/Qwen2.5-7B-Instruct` + 16 real labeled samples, and `loss`/
`grad_norm` in the training log stayed at 0 throughout. The conclusion at
the time was "16 samples is too few, GRPO's within-group reward variance
isn't enough" -- **this diagnosis later turned out to be wrong**. The
real cause was an implementation bug in `train_grpo.py::_reward_fn`: it
didn't score based on the content of each completion the model actually
sampled, but instead returned the dataset's pre-computed `qa_correct`
label unchanged for all 4 completions sampled from the same prompt --
meaning no matter what the model generated that time, the 4 reward
values within the same group were always equal, so GRPO's within-group
relative advantage (and hence the gradient) was constantly 0,
**regardless of the number of training samples** -- 27, 150, or 1500
would all have produced the same result.

A second problem also surfaced at the same time: the question
`memory_manager/policy.py`'s `TrainedPolicy` asked the model at inference
time ("please choose one action from ADD/UPDATE/DELETE/NOOP") was not the
same question it was actually trained on ("should this memory operation
be adopted?") at all -- the model was being asked to answer a question it
had never been trained to answer, so decision quality obviously couldn't
reflect the training's effect.

## Fix

1. **Changed `_reward_fn` to actually score each completion
   individually**: parse whether the model's generated text this time
   says "adopt" or "reject," and compare against the `qa_correct` label
   -- if the label is true (this fact genuinely helped the downstream QA)
   the correct answer is "adopt," if false it's "reject," and reward 1 is
   given only when they match.
   `tests/test_train_grpo.py::test_reward_fn_varies_per_completion_not_just_per_prompt`
   locks this property into a unit test, to prevent the same class of bug
   from recurring.
2. **Changed `TrainedPolicy._render_prompt` to ask exactly the same
   question as during training**: at inference time it now only asks the
   single binary question "should this be adopted?" (the only question
   the model was ever trained to answer). After adopt/reject is decided,
   the structural decision of whether it's specifically ADD or UPDATE
   reuses `RuleBasedPolicy`'s logic -- the model's own contribution is
   only the adopt/reject gate; the current training approach hasn't
   taught it to autonomously choose DELETE yet.
3. Also fixed, along the way, `TrainedPolicy` not using the GPU at
   inference time (`AutoPeftModelForCausalLM.from_pretrained` without an
   explicit `device_map` defaults to running the whole model on CPU,
   where a single 7B-model inference call takes tens of minutes; changed
   to `device_map="auto"`, matching `train_grpo.py`).

After the fix, retrained on the same 27 samples (the original 16 plus 11
more from a separate batch run against conv-41), and the log showed real
nonzero `grad_norm` (0.64, 0.52) and nonzero `reward_std` (0.05-0.16),
with `frac_reward_zero_std` dropping from a constant 1 to 0.7-0.9 on some
steps -- **indicating a real gradient signal was now present**.

## Decision comparison: 5 scenarios, rule-based vs. three versions of the trained policy

The dataset was later expanded further to 140 samples (Epic 3.1, 9
different LoCoMo conversations), and a final checkpoint was retrained on
the full 140 (420 steps, 3 epochs, real training time 4192 seconds). The
hand-checked scenarios were also expanded from 3 to 5, adding one "edge
case" -- low-value information like small talk about the weather. The
rule-based baseline's current logic is to ADD whatever comes in, but per
the business plan's vision for "what should be remembered, what should
be forgotten," this is exactly the kind of scenario the trained policy
should learn to reject.

| Scenario | Expected action | `RuleBasedPolicy` | v1 (16 samples, reward function buggy) | v3 (27 samples, reward function fixed) | **final (140 samples)** |
|---|---|---|---|---|---|
| A brand-new fact | ADD | ADD ✅ | NOOP ❌ | ADD ✅ | ADD ✅ |
| An exact duplicate fact | NOOP | NOOP ✅ | NOOP ✅ | NOOP ✅ | NOOP ✅ |
| A conflicting fact (changed jobs) | UPDATE | UPDATE ✅ | UPDATE ✅ | UPDATE ✅ | UPDATE ✅ |
| A new hobby | ADD | ADD ✅ | not tested | not tested | ADD ✅ |
| **Small talk about weather (edge case)** | Uncertain; rule-based defaults to ADD | ADD | not tested | not tested | **NOOP (differs from rule-based)** |

The final checkpoint agreed exactly with the rule-based baseline on the
first 4 scenarios (4/4), and on the 5th "small talk about weather"
scenario gave a different answer from the rule-based baseline -- the
rule-based baseline mechanically ADDed this low-value information, while
the trained policy chose NOOP. **This divergence is worth recording on
its own, but shouldn't be over-interpreted**: n=1, so there's no way to
tell whether this is genuine judgment the training learned, or just how
this particular sampling happened to land; arguing that "the trained
policy has learned to reject low-value information" would need more
repeated testing across similar scenarios to hold up -- this only
honestly records the phenomenon observed.

## What this result can and can't show

**Can show**: the training pipeline (data generation → reward function →
GRPO training → inference wrapper) is now a real, self-consistent,
working loop, not just for show; a checkpoint trained on 140 real samples
is no worse than the hand-written rules on basic scenarios, and gave a
different, possibly more sensible judgment than the rule-based baseline
on at least one edge case.

**Can't show**:
- 5 hand-constructed scenarios are not a rigorous held-out-set accuracy
  comparison.
- All 140 samples were used for training, with no held-out validation
  set carved out -- "agrees with the rule-based baseline" measures
  in-training-set consistency, not generalization ability.
- "Choosing NOOP for weather small talk is more sensible" is currently
  backed by exactly 1 sample, not a statistically meaningful conclusion.
- The rule-based baseline already gets most of these scenarios right as
  it is; the trained policy's value in situations where the rule-based
  baseline clearly can't cope (e.g. needing to judge, from more complex
  context, whether to DELETE an outdated fact) hasn't been verified yet.

## Next steps

To make this result solid, what's needed is: (1) carve a genuine held-out
validation set out of the 140 samples (currently all of it goes to
training), and run a full downstream-QA-accuracy comparison on that
validation set (not a decision-agreement comparison) -- this is the
comparison form Epic 3.6 originally envisioned; (2) expand the hand-
checked scenarios to 20+, focusing on the two kinds of scenarios the
rule-based baseline is clearly weak at -- "should low-value information
be remembered" and "does an outdated fact need to be DELETEd" -- which is
the only way to see where the trained policy's real incremental value
over the rule-based baseline actually lies, rather than repeatedly
verifying scenarios the rule-based baseline already handles fine.
