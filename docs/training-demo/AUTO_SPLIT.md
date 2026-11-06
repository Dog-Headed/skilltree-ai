# 超限资料：人工包与自动拆章

路径 A：人工整理的演示包继续用于演示。仓库里如果已经有 `samples/yanan-policy-packs/`，上传和拆章都不会改写或删除它。

路径 B：个人资料 `/training/api/materials` 和单位资料 `/training/api/admin/materials` 共用同一条超限分支。PDF 超过 10 页、PPTX 超过 15 张，或 PDF / PPTX / DOCX 正文超过 12,000 字符时自动分成多段。DOCX/PPTX 仍用 Docling 声明式标题。PDF 走无布局模型的 NativePdfPipeline（低内存主机可跑）；它本身不产出标题，随后只在字号明显更大或出现稀疏的章节行时按标题分组。识别不了时按页或按长度分段，并在每段写明「拆分依据」，不把按页结果称作按标题。页数、张数和字数上限都不提高。每一章仍是一条普通 ready 资料，沿用原来的导入和课程流程。父包只说明「已自动拆分为 N 个章节」，不能整包导入。

离线生成章节时调用同一个函数，不必再写解析器：

```bash
python scripts/split_office_chapters.py 源文件.pdf chapters
```

或在 Python 里：

```python
from pathlib import Path
from app.v3.split_policy import split_document

source = Path('源文件.pdf')
for chapter in split_document(source.read_bytes(), source.name):
    target = Path('chapters') / f'{chapter.index:02d}.md'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(chapter.content, encoding='utf-8')
```

`chapter.content` 不超过 `app.v3.office_files.MAX_TEXT`。这里没有向量库，也没有另起一套检索服务。
