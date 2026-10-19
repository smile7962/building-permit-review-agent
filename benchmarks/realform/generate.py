"""Generate synthetic Seumteo-inspired PDF fixtures; NEVER use real documents."""
from pathlib import Path
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

root=Path(__file__).resolve().parent
root.mkdir(parents=True,exist_ok=True)
fonts=[
    Path('/usr/share/fonts/truetype/nanum/NanumGothic.ttf'),
    Path('C:/Windows/Fonts/malgun.ttf'),
]
font=next((x for x in fonts if x.is_file()),None)
if not font: raise SystemExit('Korean font not found. On Ubuntu install fonts-nanum; on Windows use malgun.ttf.')
pdfmetrics.registerFont(TTFont('KoreanFixture',str(font)))
for permit in (True,False):
    path=root/('permit_checkmark.pdf' if permit else 'extension_overall.pdf')
    c=canvas.Canvas(str(path),pagesize=(595,842))
    c.setTitle('Synthetic only - not an official application')
    c.setFont('KoreanFixture',15)
    c.drawString(40,802,'[합성 시험서식] 건축'+('허가' if permit else '신고')+' 신청서')
    c.setFont('KoreanFixture',10)
    y=775
    def row(label,value):
        global y
        c.drawString(42,y,label+' : '+str(value));y-=24
    row('신청 구분','건축허가' if permit else '건축신고')
    c.drawString(42,y,'건축 구분');c.drawString(130,y,'신축');c.drawString(220,y,'증축')
    c.rect(111,y-3,11,11);c.rect(200,y-3,11,11)
    x=111 if permit else 200
    c.setLineWidth(2.1);c.line(x+2,y+2,x+5,y-1);c.line(x+5,y-1,x+11,y+10)
    y-=28
    for label,value in [
      ('대지 위치','경기도 파주시 '+('합성동' if permit else '합성리')),
      ('지번','101-7' if permit else '23-8'),
      ('대지면적','420' if permit else '560'),
      ('건축면적','120' if permit else '132'),
      ('연면적','235.5' if permit else '254.30'),
      ('건폐율','28.57' if permit else '23.57'),
      ('용적률','56.07' if permit else '45.41'),
      ('주용도','단독주택'),
      ('구조','철근콘크리트구조' if permit else '경량철골구조'),
      ('지상층수','2'),('지하층수','0'),('주차대수','2'),
      ('용도지역','계획관리지역' if permit else '보전관리지역')
    ]:row(label,value)
    if permit:row('주건축물수','1')
    y-=7;c.setFont('KoreanFixture',12);c.drawString(42,y,'동별 개요 (전체 개요와 구별)')
    y-=23;c.setFont('KoreanFixture',10)
    for label,value in [
      ('1동 기존 연면적','0' if permit else '211.00'),
      ('1동 신청 부분 연면적','235.5' if permit else '43.30'),
      ('1동 신청 용도','단독주택'),
      ('층별 개요 / 1층 신청 면적','120' if permit else '27.10'),
      ('층별 개요 / 2층 신청 면적','115.5' if permit else '16.20')
    ]:row(label,value)
    c.setFont('KoreanFixture',9)
    c.drawString(42,43,'SYNTHETIC TEST - generated synthetic values only')
    c.save()
    print(path)
