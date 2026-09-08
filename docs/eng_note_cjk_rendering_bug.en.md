# Engineering note: a rendering bug only real English input could expose

> Corresponds to TASKS.md Epic 11.3. This records a real discover→locate→
> fix→verify process, not a reconstructed after-the-fact writeup -- every
> before/after output in this note comes from the same real fix.

## Discovery: only surfaced while writing the English README demo

`_relation_to_sentence()` in `retrieval/ranker.py` renders a `(subject,
predicate, object)` relation into a natural-language sentence, which gets
handed to the LLM as context. When this code was written, it assumed
Chinese input by default:

```python
return f"{subject_name}{relation.predicate}{object_name}（记录于{recorded}）。"
```

Chinese doesn't put spaces between words, so concatenating directly like
"张三任职于某公司" produces a normal Chinese sentence. This code had been
running in Chinese scenarios for a long time without issue -- until the
README got an English demo added, and running the full pipeline on real
English input produced output like this for the first time:

```
Idoes AI research atCAS（记录于2026-09-05 10:34:29）。
```

"I" and "does" ran together into "Idoes", "at" and "CAS" into "atCAS", and
a Chinese "（记录于...）。" tag was still hanging off the end -- the
template always concatenated the Chinese way regardless of the input
language. **This isn't an occasional display glitch; it's the inevitable
result of a template that only ever considered CJK input from the first
line it was written** -- Chinese scenarios simply never exercised English
input, so it never surfaced.

## Locating it

Tracing up from `_relation_to_sentence()`, the problem wasn't limited to
this rendering layer: the triple-extraction system prompt in
`llm/openai_compatible.py` was also written entirely in Chinese, with no
explicit instruction to "keep the original language, don't translate."
In other words, even with the rendering layer fixed, the extraction stage
itself had no language-agnostic guarantee when fed English text. These two
spots (rendering + extraction prompt) are two symptoms of the same root
cause: **the whole pipeline was "Chinese-first" by design, with no
explicit language detection anywhere**.

There's also no language field on the `Relation`/`Entity` models to check
-- extraction never recorded "what language is this triple in," so
rendering naturally has no such information to draw on either. The only
way to fix it was to detect the language directly on the assembled text at
render time, rather than relying on a ready-made language tag field.

## Fix

Added a Unicode-codepoint-range-based CJK detector in `ranker.py`:

```python
_CJK_RANGES = (
    (0x4E00, 0x9FFF),  # CJK Unified Ideographs
    (0x3400, 0x4DBF),  # CJK Unified Ideographs Extension A
    (0x3000, 0x303F),  # CJK punctuation
    (0xFF00, 0xFFEF),  # halfwidth/fullwidth forms
)

def _is_cjk_text(text: str) -> bool:
    return any(
        any(start <= ord(ch) <= end for start, end in _CJK_RANGES) for ch in text
    )
```

`_relation_to_sentence()` now checks this before assembling the sentence:
Chinese input still gets the original no-space concatenation + Chinese
timestamp tag, non-Chinese input gets space-separated concatenation + an
English timestamp tag:

```python
if _is_cjk_text(f"{subject_name}{relation.predicate}{object_name}"):
    return f"{subject_name}{relation.predicate}{object_name}（记录于{recorded}）。"
return f"{subject_name} {relation.predicate} {object_name} (recorded at {recorded})."
```

The extraction system prompt in `openai_compatible.py` was also updated to
explicitly require the model to "keep the extracted subject/predicate/
object in the same language as the source text -- do not translate," and
the existing "fold the date into the predicate" technique got an English
example added alongside the Chinese one it already had.

## Verification

After the fix, a real call to DeepSeek on the same English input turned
the README demo's output from:

```
Idoes AI research atCAS（记录于2026-09-05 10:34:29）。Idoes AI research inPython（记录于2026-09-05 10:34:29）。
```

into:

```
I do AI research at CAS (recorded at 2026-09-05 10:40:00).I do AI research mostly in Python (recorded at 2026-09-05 10:40:00).
```

At the unit-test level, `tests/test_ranker.py` gained a regression test
specifically covering English concatenation
(`test_build_context_spaces_english_sentences_instead_of_running_words_together`),
and the existing dedup/out-of-scope test that used single-letter Latin
names (`a`/`b`/`c`) was switched to CJK names, so that test keeps testing
only "dedup/out-of-scope" and doesn't get entangled with the newly added
"concatenate by language" logic. The README's "known limitations" section,
which had honestly admitted that "retrieved-context rendering and triple
extraction are currently Chinese-first," also had that line removed after
this fix -- it's no longer a known gap to disclose.

## A more general lesson

The reason this bug survived undetected for so long is that **test and
demo scenarios only ever used Chinese input** -- and in Chinese, "no-space
concatenation" happens to be correct behavior, which masked the template's
underlying assumption that "input is CJK." Only actually running the
end-to-end pipeline in a different language exposed this kind of
"overfit to one input distribution" problem -- which is also why this fix
didn't stop at "the code logic makes sense now" and instead insisted on
verifying the output with a real DeepSeek API call, rather than confirming
the fix worked through code review alone.
