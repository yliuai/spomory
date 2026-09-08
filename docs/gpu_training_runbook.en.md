# Epic 3.4-3.6: GPU training -- verified end-to-end

Used `10.2.29.91` (2×NVIDIA TITAN RTX 24GB, CentOS 8), with the project
deployed at `/mnt/coding/memory-core` (not `/root` -- see the "disk/
cache" section below for why). The full, honest results and analysis are
in `docs/memory_manager_eval.md`; this document only records the
deployment process and three real gotchas hit along the way, to save
time on the next reproduction or when moving to a different machine.

## Three real gotchas hit during deployment

1. **The root partition was too small, and pip/HF caches default to
   writing there**: `/` (`cl-root`) is only 50GB, and this machine also
   runs other people's projects, so installing the full torch+CUDA stack
   at one point pushed `/` to 88% full. Fix: moved `~/.cache` (uv/pip/
   huggingface/torch caches) entirely to `/mnt/coding/cache` (492GB, only
   a small fraction used) and symlinked it back, plus added `HF_HOME`/
   `UV_CACHE_DIR` in `~/.bashrc` pointing at the new path. **If you keep
   installing things on this machine, the cache is already safe -- no
   further action needed.**
2. **torch's default CUDA version was newer than the driver**: `uv pip
   install -e ".[rl]"` by default pulled torch 2.14.0, which is bound to
   the CUDA 13 runtime, but the driver version (570.133.07) only supports
   up to CUDA 12.8 -- `torch.cuda.is_available()` returned `False`,
   reporting "driver too old." Fix: `uv pip install 'torch==2.6.0'
   --reinstall-package torch --reinstall-package nvidia-cuda-runtime-cu12`,
   which automatically switches to a version bound to the CUDA 12.4
   runtime, compatible with the driver.
3. **transformers silently offloaded some layers to the "meta" device
   when running a 7B model on a single GPU**: with only one 24GB card in
   use (`CUDA_VISIBLE_DEVICES=0`), `from_pretrained`'s large-model-
   loading optimization left layers that didn't fit on the meta device
   without materializing them, and backward raised `RuntimeError: ...
   expected device meta but got cuda:0`. Fix: `train_grpo.py::
   build_trainer()` now passes `device_map="auto"` in
   `model_init_kwargs` (when a GPU is available), letting accelerate
   split the model across both cards (48GB total VRAM is plenty for a 7B
   model). The CPU-only placeholder-model smoke test
   (`tests/test_train_grpo.py`) is unaffected, since this setting only
   takes effect when `torch.cuda.is_available()`.

The model itself is pulled via ModelScope rather than connecting to
HuggingFace directly -- this server can't reach `huggingface.co`/
`hf-mirror.com` at all (mainland China network environment), but
`modelscope.cn` connects directly. `Qwen/Qwen2.5-7B-Instruct` is Alibaba's
own model, with official weights hosted on ModelScope, so downloading
from there is faster and more reliable than going through a mirror site.

## Real training runs already completed

```bash
ssh root@10.2.29.91
cd /mnt/coding/memory-core
.venv/bin/python -m memory_core.memory_manager.train_grpo \
    --base-model /mnt/coding/cache/modelscope/models/Qwen--Qwen2.5-7B-Instruct/snapshots/master \
    --dataset benchmarks/data/memory_ops_train.jsonl \
    --output-dir /mnt/coding/memory-core/checkpoints/memory-grpo-lora
```

3 epochs, 48 steps, produced a real checkpoint, but `loss`/`grad_norm`
stayed at 0 throughout -- **16 training samples was too few for GRPO**,
the within-group reward variance across the 4 samples was 0, so there
was no real gradient. The full analysis and the real `TrainedPolicy` vs.
`RuleBasedPolicy` comparison results are in
`docs/memory_manager_eval.md`; the conclusion is that the trained policy
was not yet better than the rule-based baseline at that point.

## Next step: a larger dataset is needed to actually verify whether GRPO helps

`benchmarks/data/memory_ops_train.jsonl` (16 samples, LoCoMo conv-30
first 40 turns) and `benchmarks/data/memory_ops_train_conv3.jsonl`
(LoCoMo conv-41 first 70 turns, a separate independent batch, used to
avoid overlapping with conv-26 which the main 4.1/4.2 benchmark run
uses) are both generated with real LLM extraction + QA verification, not
placeholder data. To expand the dataset to the ~150-sample scale TASKS.md
suggests, the approach is to rerun the generation script against more
LoCoMo conversations (how many "labeled samples" each conversation
produces depends on how many turns end up cited as evidence by
downstream QA pairs -- not every turn becomes a training sample). Once
the dataset is large enough for GRPO's within-group reward to show real
variance, retraining and rerunning the comparison evaluation in
`docs/memory_manager_eval.md` is what would produce a meaningful
conclusion about "does the trained policy outperform the rule-based
baseline."
