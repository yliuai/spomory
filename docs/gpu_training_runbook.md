# Epic 3.4-3.6：GPU 训练——已跑通，真实结果是"没学到东西"

用的是 `10.2.29.91`（2×NVIDIA TITAN RTX 24GB，CentOS 8），项目部署在
`/mnt/coding/memory-core`（不是 `/root`——见下面"磁盘/缓存"一节的原因）。
完整的诚实结果和分析在 `docs/memory_manager_eval.md`，这里只记录部署过程
和三个真实踩到的坑，方便下次复现或者换机器时少走弯路。

## 部署过程中踩到的三个真实的坑

1. **root 分区太小，pip/HF 缓存默认写在那**：`/`（`cl-root`）只有 50GB，
   这台机器上还跑着别人的其他项目，装 torch+CUDA 全家桶一度把 `/` 挤到
   88% 满。修复：把 `~/.cache`（uv/pip/huggingface/torch 缓存）整体搬到
   `/mnt/coding/cache`（492GB，只用了一小部分）然后软链接回去，并在
   `~/.bashrc` 里加了 `HF_HOME`/`UV_CACHE_DIR` 指向新路径。**如果你在这台
   机器上继续装东西，缓存已经是安全的了，不用再管。**

2. **torch 默认装的 CUDA 版本比驱动新**：`uv pip install -e ".[rl]"` 默认
   拉的 torch 2.14.0 绑定的是 CUDA 13 运行时，但驱动版本（570.133.07）
   最高只支持 CUDA 12.8——`torch.cuda.is_available()` 返回 `False`，报
   "driver too old"。修复：`uv pip install 'torch==2.6.0' --reinstall-package torch --reinstall-package nvidia-cuda-runtime-cu12`，
   会自动换成绑定 CUDA 12.4 运行时的版本，和驱动兼容。

3. **单 GPU 跑 7B 模型时 transformers 悄悄把部分层扔到 "meta" 设备**：
   只用一张 24GB 卡（`CUDA_VISIBLE_DEVICES=0`）时，`from_pretrained` 的大
   模型加载优化会把放不下的层留在 meta 设备上不实体化，backward 时报
   `RuntimeError: ... expected device meta but got cuda:0`。修复：
   `train_grpo.py::build_trainer()` 现在给 `model_init_kwargs` 传
   `device_map="auto"`（有 GPU 时），让 accelerate 把模型切分到两张卡上
   （48GB 总显存对 7B 模型绰绰有余）。CPU-only 的占位模型冒烟测试
   （`tests/test_train_grpo.py`）不受影响，因为这个设置只在
   `torch.cuda.is_available()` 时生效。

模型本身走的是 ModelScope 而不是 HuggingFace 直连——这台服务器到
`huggingface.co`/`hf-mirror.com` 都连不通（大陆网络环境），`modelscope.cn`
可以直连。`Qwen/Qwen2.5-7B-Instruct` 就是阿里自己的模型，ModelScope 上有
官方权重，下载比绕道镜像站更快也更稳。

## 已经跑过的真实训练

```bash
ssh root@10.2.29.91
cd /mnt/coding/memory-core
.venv/bin/python -m memory_core.memory_manager.train_grpo \
    --base-model /mnt/coding/cache/modelscope/models/Qwen--Qwen2.5-7B-Instruct/snapshots/master \
    --dataset benchmarks/data/memory_ops_train.jsonl \
    --output-dir /mnt/coding/memory-core/checkpoints/memory-grpo-lora
```

3 个 epoch、48 步，产出了真实 checkpoint，但 `loss`/`grad_norm` 全程为
0——**16 条训练样本对 GRPO 来说太少**，组内 4 个采样奖励方差为 0，没有
真实梯度。完整分析和 `TrainedPolicy` vs `RuleBasedPolicy` 的真实对比结果
见 `docs/memory_manager_eval.md`；结论是训练后的策略目前不如规则式基线。

## 下一步：要真正验证 GRPO 有没有用，需要更大的数据集

`benchmarks/data/memory_ops_train.jsonl`（16条，LoCoMo conv-30 前40轮）和
`benchmarks/data/memory_ops_train_conv3.jsonl`（LoCoMo conv-41 前70轮，
另一批独立样本，用于避免和主 4.1/4.2 基准跑分用的 conv-26 重叠）都是用
真实 LLM 抽取+QA 验证生成的，不是占位数据。要把数据集扩到 TASKS.md 建议
的 ~150 条规模，思路是对更多段 LoCoMo 对话重复跑生成脚本（每段对话能产出
的"标注样本"数量取决于有多少轮对话被后续问答引用为证据，不是所有轮次都
能变成一条训练样本）。数据集大到能让 GRPO 组内奖励出现方差之后，重新跑
一遍训练 + `docs/memory_manager_eval.md` 里的对比评估，才能得到有意义的
"训练后策略是否优于规则式基线"结论。
