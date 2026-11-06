"""Write within-limit chapters for one PDF, DOCX, or PPTX.

Uses the same helper as the training upload path:

    python scripts/split_office_chapters.py 源文件.pdf chapters
"""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.v3.office_files import MAX_TEXT
from app.v3.split_policy import split_document


def main():
    parser = argparse.ArgumentParser(description='把超限 PDF、DOCX 或 PPTX 拆成不超过现有字数上限的章节；不可靠标题会标明按页或按长度。')
    parser.add_argument('source')
    parser.add_argument('output')
    args = parser.parse_args()
    source = Path(args.source)
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    chapters = split_document(source.read_bytes(), source.name)
    for chapter in chapters:
        if len(chapter.content) > MAX_TEXT:
            raise SystemExit(f'第 {chapter.index} 章超过 {MAX_TEXT} 字符')
        name = f'{chapter.index:02d}.md'
        (output / name).write_text(chapter.content, encoding='utf-8')
        print(f'{name}\t{len(chapter.content)}\t{chapter.split_basis}\t{chapter.page_start or ""}-{chapter.page_end or ""}\t{chapter.title}')


if __name__ == '__main__':
    main()
