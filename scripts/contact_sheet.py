"""PDF 여러 쪽을 한 장의 모음 이미지(PNG)로 만든다. 사용: python contact_sheet.py <pdf> <out.png> <쪽번호(1부터), ...> [열수=3] [쪽당 너비=620]"""
import sys

import pymupdf

pdf, out, pages = sys.argv[1], sys.argv[2], [int(x) for x in sys.argv[3].split(",")]
cols = int(sys.argv[4]) if len(sys.argv) > 4 else 3
width = int(sys.argv[5]) if len(sys.argv) > 5 else 620

doc = pymupdf.open(pdf)
pix = []
for p in pages:
    page = doc[p - 1]
    z = width / page.rect.width
    pix.append(page.get_pixmap(matrix=pymupdf.Matrix(z, z)))
h = max(x.height for x in pix)
rows = (len(pix) + cols - 1) // cols
sheet = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, cols * width, rows * h), False)
sheet.set_rect(sheet.irect, (255, 255, 255))
for i, px in enumerate(pix):
    px = pymupdf.Pixmap(pymupdf.csRGB, px)
    px.set_origin((i % cols) * width, (i // cols) * h)
    sheet.copy(px, px.irect)
sheet.save(out)
print(out, sheet.width, sheet.height)
