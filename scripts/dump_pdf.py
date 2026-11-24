"""PDF 텍스트 덤프 (페이지 구분 포함). 사용: python -I dump_pdf.py <pdf> <out.txt>"""
import sys
import pymupdf

src, out = sys.argv[1], sys.argv[2]
doc = pymupdf.open(src)
with open(out, "w", encoding="utf-8") as w:
    for i, p in enumerate(doc):
        w.write(f"\n=====PAGE {i + 1}=====\n{p.get_text()}")
print(len(doc), "pages ->", out)
