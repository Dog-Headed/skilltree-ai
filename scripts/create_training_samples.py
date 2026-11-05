"""Rebuild the four small, entirely fictional Day 2 office samples.

Requires runtime requirements plus reportlab==4.4.4 (sample generation only).
"""
from pathlib import Path
from docx import Document
from openpyxl import Workbook
from pptx import Presentation
from pptx.util import Inches
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont


def create_samples(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    pdfmetrics.registerFont(UnicodeCIDFont('STSong-Light'))
    pdf = canvas.Canvas(str(root/'岗位手册.pdf'))
    for page, lines in enumerate([
        ['中国电信延安分公司 · 岗位手册（全部为虚构示例）', '第一章 服务工单',
         '服务专员应在收到工单后 30 分钟内首次响应。', '一般工单须在 2 个工作日内完成处理。'],
        ['第二章 交接与复核', '每天 17:30 前完成当日工单交接。',
         '交接清单包括工单编号、处理状态、下一责任人。']],1):
        pdf.setFont('STSong-Light', 15)
        for index, text in enumerate(lines):
            pdf.drawString(48, 780-index*45, text)
        pdf.setFont('STSong-Light', 10)
        pdf.drawString(48,40,f'第 {page} 页 · 虚构示例')
        pdf.showPage()
    pdf.save()
    doc = Document()
    doc.add_heading('中国电信延安分公司学习制度（虚构示例）',0)
    doc.add_heading('第一条 学习安排',1)
    doc.add_paragraph('每位新员工须在入职后 5 个工作日内完成基础制度学习。')
    doc.add_heading('第二条 记录与复核',1)
    doc.add_paragraph('每周五 16:00 前提交学习记录，由直属导师复核。')
    table = doc.add_table(rows=1, cols=3)
    for cell,text in zip(table.rows[0].cells,['事项','时限','责任人']):cell.text=text
    for values in [['学习记录留存','180 天','学习管理员'],['异议反馈','2 个工作日','直属导师']]:
        for cell,text in zip(table.add_row().cells,values):cell.text=text
    doc.save(root/'培训制度.docx')
    book = Workbook()
    sheet = book.active
    sheet.title='岗位职责'
    for row in [['岗位','职责','响应时限（分钟）','复核频率'],
                ['服务专员','工单首次响应',30,'每日'],['交付专员','交付检查',60,'每周'],
                ['学习管理员','学习记录复核',120,'每周五']]:sheet.append(row)
    sheet = book.create_sheet('补充说明')
    sheet.append(['事项','数值','单位'])
    sheet.append(['记录保留',180,'天'])
    book.save(root/'岗位职责表.xlsx')
    deck=Presentation()
    for title,lines in [('入职第 1 天',['中国电信延安分公司入职流程（虚构示例）','09:00 到综合服务台报到。','领取设备后核对资产编号。']),
                        ('入职第 2 天',['10:00 参加信息安全学习。','完成账号开通和双因素认证。']),
                        ('入职第 5 天',['17:00 前向导师提交学习记录。','导师核对基础制度学习完成情况。'])]:
        slide=deck.slides.add_slide(deck.slide_layouts[1])
        slide.shapes.title.text=title
        slide.placeholders[1].text='\n'.join(lines)
    deck.save(root/'入职流程.pptx')


if __name__=='__main__':
    create_samples(Path(__file__).resolve().parents[1]/'docs/training-demo/samples')
