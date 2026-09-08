# Epic 5.1/5.3: image input processing and multimodal-feature verification

Corresponds to the honest scope defined in the business plan's "II.3.
Multimodal processing": it doesn't claim "native cross-modal
extraction," and puts engineering effort specifically into one concrete
piece: "using raw image features to cross-verify candidate triples."
What follows records that piece's real implementation and real test
results, not placeholder/synthetic data.

## Pipeline (actually run end-to-end, not pseudocode)

1. **Captioning** (`multimodal/image_captioning.py::OpenAICompatibleVisionProvider`):
   uses an OpenAI-compatible model with vision input support (this run
   used DeepSeek's `deepseek-v4-flash-vision-exp`) to turn an image into
   a text description.
2. **Extraction**: feeds the description text into Epic 1.4's already-
   working `LLMProvider.extract_triples()` -- fully reused, with no
   separate extraction logic written for image input.
3. **CLIP verification** (`multimodal/clip_verification.py::ClipVerifier`):
   uses a real open-source CLIP model (`openai/clip-vit-base-patch32`) to
   compute the cosine similarity between a candidate triple's text and
   the original image, as a secondary verification score.

## Test images: 10 real images, hand-labeled expected relations

The images come from picsum.photos (backed by real Unsplash photos --
each numeric ID maps to a fixed real photo, so it's reproducible). I
looked at each one individually with the Read tool and labeled the
expected entity relations myself, stored in
`benchmarks/data/multimodal_ground_truth.json` (a black puppy, a pug in a
blanket, a lion close-up, a group of walruses, strawberries, a jellyfish,
a sea cliff, a castle, a person under a waterfall, a rocky cliff face --
covering distinctly different themes like animals, food, scenery, and
people, with visually distinct content from each other).

## Result 1: the real pipeline's extraction quality on these 10 images is high

Ran the full captioning→extraction pipeline
(`benchmarks/results/multimodal_real_extraction.json`), and all 10 images
produced accurate triples that matched the image content. For example,
the black puppy image:

```
caption: A black puppy sits on an old wooden floor with horizontal grain,
         looking up at the camera.
triple: (puppy, sits on, old wooden floor with horizontal grain)
triple: (puppy, looks up at, camera)
triple: (puppy, is, black)
```

Semantically consistent with the hand-labeled expected relations ("puppy
sits on wooden floor," "puppy is black labrador"). All 10 images were
like this -- **this is itself an honest finding**: on this batch of test
images, the vision model's captioning quality was already high, and no
naturally occurring hallucinations/errors were observed, so this batch of
real extraction results can't directly demonstrate a case of "CLIP
verification caught a real error."

## Result 2: constructed distractors verify the CLIP verification mechanism itself does work

Since real extraction didn't naturally produce errors, a difficulty-
controlled experiment was used to directly test "does this verification
mechanism itself have discriminating power"
(`benchmarks/multimodal_eval.py`): each image was paired with 2 real
candidate triples + 2 "distractor" triples borrowed from **another**
image's real triples (grammatically/semantically perfectly coherent text,
but not matching this image's actual content -- exactly the kind of
error multimodal verification is meant to catch: the candidate triple
itself has no grammar/semantic issue, it just doesn't correspond to this
particular image).

| Method | Accuracy |
|---|---|
| Text description only (no access to the image, must accept the extraction result outright) | 50.00% (20 of 40 candidates true, the natural ceiling) |
| CLIP secondary verification (take the top-N by score as true) | **100.00%** (40/40 all judged correctly) |

Raw data: [`multimodal_eval.json`](../benchmarks/results/multimodal_eval.json).
Per-item scores are in that file's `per_image` -- for every single image,
the 2 real triples' CLIP scores were strictly higher than the 2 distractor
triples', with no exceptions across all 10 images.

## Honest disclosure of this result's limitations

**The 100% separation is partly because the test design skews toward
"easy mode"**: the distractors were borrowed from a completely different-
themed image (e.g. using "lion" triples to distract a "puppy" image),
and it's relatively easy for CLIP to distinguish two semantically very
different scenes. Real-world hallucinations that matter more tend to be
subtler -- e.g. getting the color, position, or count wrong within the
same scene ("black puppy" misstated as "brown puppy," where both use
largely the same vocabulary and differ in only one attribute). Whether
CLIP can still achieve 100% on this finer-grained kind of distinction
hasn't been tested this time; it would take a rerun with harder
distractors to find out.

**What was verified here is "does the mechanism work," not "how much did
the production error rate drop"** -- because real extraction didn't make
any errors on this batch of images, there's no real case available to
compare error rates "before vs. after verification."

## Epic 5.2 (voice): kept deferred per the plan's own recommendation

TASKS.md 5.2 is itself labeled "optional, significant effort, recommend
deferring," and no work went into it this round -- audio input involves
an additional ASR transcription step and audio-embedding-model selection,
clearly more work than the image branch, and stays deferred for now; this
is not an oversight.
