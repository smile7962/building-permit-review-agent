"""Regenerate PUBLIC, SYNTHETIC examples. Developer-only: artifact_tool + ReportLab.

Not exact Seumteo originals or approved official forms. Never include real citizen data.
"""
from pathlib import Path
from reportlab.pdfgen.canvas import Canvas
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase import pdfmetrics
from reportlab.lib.pagesizes import A4

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'practical_fixtures'
OUT.mkdir(exist_ok=True)
pdfmetrics.registerFont(UnicodeCIDFont('HYSMyeongJo-Medium'))


def add_line(c,x,y,text,size=10):
    c.setFont('HYSMyeongJo-Medium',size);c.setFillColorRGB(0.12,0.21,0.35);c.drawString(x,y,text)


def work_check(c,name,selected=True):
    y=696
    add_line(c,55,y,'건축구분',10)
    for i,opt in enumerate(['신축','증축','개축','재축','이전','대수선']):
        x=153+i*67
        c.setLineWidth(.7);c.setStrokeColorRGB(.24,.37,.55);c.rect(x-20,y+0,10,10,stroke=1,fill=0)
        add_line(c,x,y,opt,9)
        if selected and opt==name:
            # A tiny filled path is deliberately distinct from the outline.
            p=c.beginPath();p.moveTo(x-17,y+3);p.lineTo(x-12,y+3);p.lineTo(x-12,y+8);p.lineTo(x-17,y+8);p.close()
            c.setFillColorRGB(.06,.28,.65);c.drawPath(p,stroke=0,fill=1)

def write_pdf(name, permit=True, marked=True):
    c=Canvas(str(OUT/name),pagesize=A4,pageCompression=1)
    add_line(c,55,790,'[모의 합성 테스트 전용] 개인정보 없는 세움터 유사 서식',10)
    add_line(c,55,764,'건축(변경)허가신청서' if permit else '건축(변경)신고서',18)
    add_line(c,55,736,'Ⅰ. 전체 개요',12)
    work_check(c,'신축' if permit else '증축',marked)
    loc='경기도 파주시 가상동' if permit else '경기도 파주시 임시리'
    lot='101-7' if permit else '23-8'
    entries=[
       ('대지위치',loc),('지번',lot),('대지면적', '420' if permit else '560'),
       ('건축면적', '120' if permit else '132'),('연면적합계','235.50' if permit else '254.30'),
       ('건폐율','28.57' if permit else '23.57'),('용적률','56.07' if permit else '45.41'),
       ('⑤주용도','단독주택'),('주구조','철근콘크리트구조' if permit else '경량철골구조'),
       ('지상층수','2'),('지하층수','0'),
       ('주건축물수','1 동' if permit else ''),
       ('총주차대수','2 대'),('용도지역','계획관리지역' if permit else '보전관리지역'),
       ('특이사항','[모의] ' + ('신축' if permit else '증축')+' 검증 · 실제 민원 아님')
    ]
    y=660
    for label,val in entries:
        add_line(c,65,y,label,10)
        if val: add_line(c,255,y,val,10)
        y-=28
    c.line(55,224,540,224)
    add_line(c,60,207,'주의: 합성 데이터이며 민원번호·연락처·실제 대지 주소가 없습니다.',9)
    c.showPage()
    add_line(c,60,787,'Ⅱ. 동별 개요',13)
    add_line(c,65,745,'동명칭 및 번호  주건축물제1동',10)
    add_line(c,65,702,'주용도 단독주택',10)
    add_line(c,65,668,'주구조 '+('철근콘크리트구조' if permit else '경량철골구조'),10)
    add_line(c,65,634,'110 ※연면적(㎡) 40.00' if not permit else '※연면적(㎡) 235.50',10)
    add_line(c,65,600,'100 ※건축면적(㎡) 20.00' if not permit else '※건축면적(㎡) 120',10)
    add_line(c,60,540,'표 오른쪽 숫자는 증축 신청 부분으로, 전체 연면적과 다릅니다.',9)
    c.showPage()
    add_line(c,60,787,'Ⅲ. 층별 개요',13)
    add_line(c,65,749,'동명칭 및 번호 주건축물제1동',10)
    if permit:
        for y,txt,area in [(713,'1 신축 단독주택','120'),(640,'2 신축 단독주택','115.50')]:
            add_line(c,75,y,txt);add_line(c,84,y-27,'철근콘크리트구조');add_line(c,96,y-49,area)
    else:
        for y,txt,area in [(713,'110 1 증축 단독주택','25.00'),(640,'100 2 증축 단독주택','15.00')]:
            add_line(c,75,y,txt);add_line(c,84,y-27,'경량철골구조');add_line(c,96,y-49,area)
    add_line(c,60,487,'Ⅳ. 대수선 개요',10)
    c.save()

write_pdf('synthetic_permit_house.pdf',True)
write_pdf('synthetic_notice_extension.pdf',False)
write_pdf('synthetic_unmarked_permit.pdf',True,False)

from artifact_tool import Workbook, SpreadsheetFile
wb=Workbook.create()
page1=wb.worksheets.add('Page 1')
rows=[
    ['[모의 합성 테스트] 건축(변경)허가신청서','','','',''],
    ['Ⅰ. 전체 개요','','','',''],
    ['건축구분','☑ 신축   □ 증축   □ 개축   □ 재축   □ 이전   □ 대수선','','',''],
    ['대지위치','경기도 파주시 테스트동','','',''],
    ['지번','88-12','','',''],
    ['대지면적','1230','','',''],
    ['건축면적','790','','',''],
    ['연면적합계','5410','','',''],
    ['건폐율','64.23','','',''],
    ['용적률','282.93','','',''],
    ['⑤주용도','자동차관련시설(주차장)','','',''],
    ['주구조','철골철근콘크리트구조','','',''],
    ['지하층수','2','','',''],
    ['지상층수','5','','',''],
    ['주건축물수','1','','',''],
    ['총주차대수','110','','',''],
    ['용도지역','일반상업지역','','',''],
    ['특이사항','[모의] 대규모 주차장 사용 · 실제 주소 아님','','','']]
page1.get_range('A1:E18').values=rows
page1.get_range('A1:E1').format={'fill':'#183458','font':{'color':'#FFFFFF','bold':True},'row_height':25}
page1.get_range('A2:E2').format={'fill':'#E5EEF8','font':{'bold':True}}
page1.get_range('A1:A18').format.column_width=23
page1.get_range('B1:B18').format.column_width=52
page3=wb.worksheets.add('Page 3')
page3.get_range('A1:D7').values=[
    ['Ⅱ. 동별 개요','','',''],
    ['', '동명칭 및 번호', '주건축물제1동',''],
    ['', '주용도', '자동차관련시설(주차장)',''],
    ['', '주구조', '철골철근콘크리트구조',''],
    ['', '※건축면적(㎡)', '790',''],
    ['', '※연면적(㎡)', '5410',''],
    ['', '층수', '지하:2층 지상:5층','']]
page3.get_range('B1:B7').format.column_width=29
page3.get_range('C1:C7').format.column_width=36
page4=wb.worksheets.add('Page 4')
page4.get_range('A1:E6').values=[
    ['Ⅲ. 층별 개요','','','',''],
    ['동명칭 및 번호 주건축물제1동','','','',''],
    ['-2','신축','철골철근콘크리트구조','주차장','600'],
    ['-1','신축','철골철근콘크리트구조','주차장','800'],
    ['1','신축','철골철근콘크리트구조','주차장','790'],
    ['2','신축','철골철근콘크리트구조','주차장','805']]
page4.get_range('B1:B6').format.column_width=18
page4.get_range('C1:C6').format.column_width=26
page4.get_range('D1:D6').format.column_width=22
SpreadsheetFile.export_xlsx(wb).save(str(OUT/'synthetic_permit_parking.xlsx'))
print('CREATED',[(x.name,x.stat().st_size) for x in OUT.iterdir()])
