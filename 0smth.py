from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

font_path = r"C:\WORK\sova_rest_bot\sova_rest_bot-master\src\basic\revenue_analysis\DejaVuSans.ttf"
pdfmetrics.registerFont(TTFont('DejaVuSans', font_path))