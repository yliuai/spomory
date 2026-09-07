# 工程笔记：一个只有真实英文输入才会暴露的渲染 bug

> 对应 TASKS.md Epic 11.3。记录一次真实的发现→定位→修复→验证过程，不是
> 事后补写的复盘——这份笔记里的每一段前后输出都来自同一次真实修复。

## 发现：写英文版 README demo 时才暴露的问题

`retrieval/ranker.py` 里 `_relation_to_sentence()` 负责把一条 `(主体, 谓语,
客体)` 关系渲染成一句自然语言，拼给 LLM 当上下文用。这段代码写的时候
默认输入是中文：

```python
return f"{subject_name}{relation.predicate}{object_name}（记录于{recorded}）。"
```

中文里词与词之间本来就不加空格，"张三任职于某公司" 直接拼接是正常的中文
句子。这份代码在中文场景下用了很久，没出过问题——直到给 README 补英文版
demo、用真实的英文输入跑一遍完整流程，才第一次看到这样的输出：

```
Idoes AI research atCAS（记录于2026-09-05 10:34:29）。
```

"I" 和 "does" 粘在一起变成 "Idoes"，"at" 和 "CAS" 粘成 "atCAS"，句尾还挂着
一个中文的"（记录于...）。"标签——不管输入是什么语言，模板永远按中文的
拼接方式处理。**这不是一个偶发的显示问题，是这段模板从写下第一行代码起
就只考虑了 CJK 输入的必然结果**，只是中文场景一直用不到英文输入，所以
一直没暴露出来。

## 定位

顺着 `_relation_to_sentence()` 往上查，发现问题不止在渲染这一层：`llm/
openai_compatible.py` 里的三元组抽取系统提示词本身也是纯中文写的，没有
明确告诉模型"保持原文语言，不要翻译"——也就是说，即使渲染层修好了，输入
英文文本时抽取阶段本身也没有语言无关的保证。这两处（渲染 + 抽取提示词）
是同一个根因的两个症状：**整条流水线从设计上就是"中文优先"，没有一处
显式做了语言判断**。

`Relation`/`Entity` 模型上也没有任何语言字段可以查——抽取的时候没有记录
"这条三元组是什么语言"，渲染的时候自然也拿不到这个信息。要修，只能在
渲染阶段直接对拼出来的文本做语言检测，而不是指望有一个现成的语言标记
字段。

## 修复

在 `ranker.py` 里加了一个基于 Unicode 码位范围的 CJK 检测函数：

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

`_relation_to_sentence()` 拼句子之前先用这个函数判断一次，中文走原来的
无空格拼接 + 中文时间戳标签，非中文走加空格拼接 + 英文时间戳标签：

```python
if _is_cjk_text(f"{subject_name}{relation.predicate}{object_name}"):
    return f"{subject_name}{relation.predicate}{object_name}（记录于{recorded}）。"
return f"{subject_name} {relation.predicate} {object_name} (recorded at {recorded})."
```

同时把 `openai_compatible.py` 的抽取系统提示词也改了，明确要求模型"抽取出
的 subject/predicate/object 请保持和原文一致的语言，不要翻译"，并且给
"日期折叠进谓语"这个已有技巧同时补了一个英文例子（原来只有中文例子）。

## 验证

改完之后，真实调用一次 DeepSeek 跑同样的英文输入，README 里的 demo 输出
从：

```
Idoes AI research atCAS（记录于2026-09-05 10:34:29）。Idoes AI research inPython（记录于2026-09-05 10:34:29）。
```

变成：

```
I do AI research at CAS (recorded at 2026-09-05 10:40:00).I do AI research mostly in Python (recorded at 2026-09-05 10:40:00).
```

单元测试层面，`tests/test_ranker.py` 新增了专门覆盖英文拼接的回归测试
（`test_build_context_spaces_english_sentences_instead_of_running_words_together`），
同时把原来用单字母拉丁名字（`a`/`b`/`c`）做去重/越界测试的用例换成了 CJK
名字，让那条用例继续只测"去重/越界"这一件事，不再和新加的"按语言拼接"
逻辑混在一起。README 里原来"已知局限"一节坦承"检索上下文渲染和三元组
抽取目前是中文优先"的那段话，也在这次修复后删掉了——不再是一个需要
承认的已知缺陷。

## 更通用的教训

这个 bug 能存在这么久而不被发现，根本原因是**测试和 demo 场景一直只用
中文输入**，中文场景下"无空格拼接"恰好是正确行为，掩盖了模板本身"假设
输入是 CJK"这个前提。只有真正换一种语言跑一遍端到端流程，这类"对某个
输入分布过拟合"的问题才会暴露——这也是为什么这次修复没有满足于"改完
代码逻辑上说得通"就收工，而是坚持用真实的 DeepSeek API 调用去验证输出，
而不是靠人工审查代码来确认修复有效。
