# yimai

AI个人记忆方案及配套工程任务清单。

## 参考论文（`paper/`）

以下论文对应《AI个人记忆方案》「二、核心差异化技术方案」章节中引用的技术路线，已下载至 [paper/](paper/) 目录，文件名含 arXiv ID 便于溯源。

| 论文 | arXiv | 对应技术点 |
|---|---|---|
| [HippoRAG: Neurobiologically Inspired Long-Term Memory for Large Language Models](paper/2405.14831-HippoRAG_Neurobiologically_Inspired_Long-Term_Memory_for_LLMs.pdf) | [2405.14831](https://arxiv.org/abs/2405.14831) | 检索架构基础：模拟海马体记忆机制，离线抽取三元组构建知识图谱，查询时用个性化PageRank做一次性多跳传播，替代逐跳迭代式RAG |
| [From RAG to Memory: Non-Parametric Continual Learning for Large Language Models（HippoRAG 2）](paper/2502.14802-HippoRAG2_From_RAG_to_Memory.pdf) | [2502.14802](https://arxiv.org/abs/2502.14802) | HippoRAG 升级版：查询直接映射到三元组而非实体节点，Recall@5 相比映射到节点提升12.5%，关联记忆能力提升约7% |
| [LightRAG: Simple and Fast Retrieval-Augmented Generation](paper/2410.05779-LightRAG_Simple_and_Fast_Retrieval-Augmented_Generation.pdf) | [2410.05779](https://arxiv.org/abs/2410.05779) | 双层增量图：实体层与关系层独立建模，新数据仅需抽取+合并、无需整图重建，检索延迟0.5-2秒、成本为GraphRAG的1/5到1/10 |
| [From Local to Global: A Graph RAG Approach to Query-Focused Summarization](paper/2404.16130-GraphRAG_From_Local_to_Global.pdf) | [2404.16130](https://arxiv.org/abs/2404.16130) | 微软 GraphRAG，作为对比基线：效果强但索引成本高（每百万Token 30-100美元，耗时30-120分钟），每次更新需重建整张图，不适合持续增长的个人记忆场景 |
| [Memory-R1: Enhancing Large Language Model Agents to Manage and Utilize Memories via Reinforcement Learning](paper/2508.19828-Memory-R1_Enhancing_LLM_Agents_via_RL.pdf) | [2508.19828](https://arxiv.org/abs/2508.19828) | 记忆管理路线选型：用 PPO/GRPO 训练决定记忆增/删/改/不变的管理器，仅用152条标注问答对，在LoCoMo基准上相对Mem0提升48%的F1值——本方案 Epic 3 采用的技术路线 |
| [Mem-α: Learning Memory Construction via Reinforcement Learning](paper/2509.25911-Mem-alpha_Learning_Memory_Construction_via_RL.pdf) | [2509.25911](https://arxiv.org/abs/2509.25911) | 记忆管理对比方案：三分记忆结构，GRPO配合四项奖励训练，562条训练样本，32张H100训练3天，门槛高于Memory-R1 |
| [VAT-KG: Knowledge-Intensive Multimodal Knowledge Graph Dataset for Retrieval-Augmented Generation](paper/2506.21556-VAT-KG_Multimodal_Knowledge_Graph_Dataset.pdf) | [2506.21556](https://arxiv.org/abs/2506.21556) | 多模态处理诚实定位的依据：印证目前没有团队真正实现"原生跨模态"实体关系抽取，所有多模态知识图谱构建本质仍是先转文字描述再抽取三元组 |
| [Evaluating Very Long-Term Conversational Memory of LLM Agents（LoCoMo）](paper/2402.17753-LoCoMo_Evaluating_Very_Long-Term_Conversational_Memory.pdf) | [2402.17753](https://arxiv.org/abs/2402.17753) | 公开评测基准之一，用于 Epic 3（记忆管理训练数据/对比评估）与 Epic 4（技术验证跑分） |
| [LongMemEval: Benchmarking Chat Assistants on Long-Term Interactive Memory](paper/2410.10813-LongMemEval_Benchmarking_Chat_Assistants.pdf) | [2410.10813](https://arxiv.org/abs/2410.10813) | 公开评测基准之一，用于 Epic 4 搭建检索+记忆管理全流程 harness 并产出可复现指标 |
