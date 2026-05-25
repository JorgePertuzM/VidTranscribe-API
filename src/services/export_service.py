# src/services/export_service.py
"""
Servicio de exportación de resúmenes a PDF y Word.
"""
import io
import re
from typing import Tuple
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.enums import TA_JUSTIFY, TA_LEFT, TA_CENTER
from docx import Document
from docx.shared import Pt, Inches, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
import markdown
from html.parser import HTMLParser

class MarkdownToReportLab:
    """Convierte Markdown a elementos de ReportLab."""
    
    def __init__(self):
        self.styles = getSampleStyleSheet()
        self._setup_custom_styles()
    
    def _setup_custom_styles(self):
        """Configura estilos personalizados para el PDF."""
        # Título principal (H1)
        self.styles.add(ParagraphStyle(
            name='CustomTitle',
            parent=self.styles['Heading1'],
            fontName='Helvetica-Bold',
            fontSize=24,
            spaceAfter=30,
            alignment=TA_CENTER,
            textColor=colors.HexColor('#1a1a2e')
        ))
        
        # Título H2
        self.styles.add(ParagraphStyle(
            name='CustomHeading2',
            parent=self.styles['Heading2'],
            fontName='Helvetica-Bold',
            fontSize=16,
            spaceBefore=20,
            spaceAfter=10,
            textColor=colors.HexColor('#16213e')
        ))
        
        # Título H3
        self.styles.add(ParagraphStyle(
            name='CustomHeading3',
            parent=self.styles['Heading3'],
            fontName='Helvetica-Bold',
            fontSize=14,
            spaceBefore=15,
            spaceAfter=8,
            textColor=colors.HexColor('#0f3460')
        ))
        
        # Texto normal
        self.styles.add(ParagraphStyle(
            name='CustomNormal',
            parent=self.styles['Normal'],
            fontName='Helvetica',
            fontSize=11,
            leading=14,
            alignment=TA_JUSTIFY,
            spaceAfter=6
        ))
        
        # Lista
        self.styles.add(ParagraphStyle(
            name='CustomList',
            parent=self.styles['Normal'],
            fontName='Helvetica',
            fontSize=11,
            leading=14,
            leftIndent=20,
            spaceAfter=4
        ))
    
    def parse_markdown(self, markdown_text: str) -> list:
        """Convierte Markdown a lista de elementos ReportLab."""
        elements = []
        lines = markdown_text.split('\n')
        i = 0
        
        while i < len(lines):
            line = lines[i].strip()
            
            if not line:
                i += 1
                continue
            
            # Título H1
            if line.startswith('# ') and not line.startswith('## '):
                text = line[2:].strip()
                elements.append(Paragraph(text, self.styles['CustomTitle']))
                elements.append(Spacer(1, 0.3 * cm))
            
            # Título H2
            elif line.startswith('## '):
                text = line[3:].strip()
                elements.append(Paragraph(text, self.styles['CustomHeading2']))
            
            # Título H3
            elif line.startswith('### '):
                text = line[4:].strip()
                elements.append(Paragraph(text, self.styles['CustomHeading3']))
            
            # Listas (emojis como 📋, 🎯, ❓, 🔍)
            elif line.startswith('- ') or line.startswith('* '):
                text = line[2:].strip()
                # Limpiar emojis para mejor visualización
                clean_text = self._clean_emoji(text)
                elements.append(Paragraph(f'• {clean_text}', self.styles['CustomList']))
            
            # Texto normal
            else:
                # Limpiar markdown básico
                clean_line = self._clean_inline_markdown(line)
                elements.append(Paragraph(clean_line, self.styles['CustomNormal']))
            
            i += 1
        
        return elements
    
    def _clean_emoji(self, text: str) -> str:
        """Limpia o reemplaza emojis para mejor visualización."""
        emoji_map = {
            '📋': '[Lista]',
            '🎯': '[Objetivo]',
            '❓': '[Pregunta]',
            '🔍': '[Término]',
            '✅': '[OK]',
            '⚠️': '[Atención]',
        }
        for emoji, replacement in emoji_map.items():
            text = text.replace(emoji, replacement)
        return text
    
    def _clean_inline_markdown(self, text: str) -> str:
        """Convierte markdown inline a HTML básico para ReportLab."""
        # Negritas **texto** -> <b>texto</b>
        text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', text)
        # Itálicas *texto* -> <i>texto</i>
        text = re.sub(r'\*(.*?)\*', r'<i>\1</i>', text)
        return text


def generate_pdf(summary_content: str, title: str) -> bytes:
    """
    Genera un PDF a partir del contenido del resumen en Markdown.
    
    Args:
        summary_content: Contenido del resumen en formato Markdown
        title: Título del video
        
    Returns:
        bytes: Contenido del PDF
    """
    buffer = io.BytesIO()
    
    # Configurar documento
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=2.5*cm,
        leftMargin=2.5*cm,
        topMargin=2.5*cm,
        bottomMargin=2.5*cm,
        title=f"Resumen: {title}"
    )
    
    # Parsear Markdown
    parser = MarkdownToReportLab()
    story = parser.parse_markdown(summary_content)
    
    # Construir PDF
    doc.build(story)
    
    return buffer.getvalue()


def generate_word(summary_content: str, title: str) -> bytes:
    """
    Genera un documento Word a partir del contenido del resumen en Markdown.
    
    Args:
        summary_content: Contenido del resumen en formato Markdown
        title: Título del video
        
    Returns:
        bytes: Contenido del documento Word
    """
    doc = Document()
    
    # Configurar márgenes
    sections = doc.sections
    for section in sections:
        section.top_margin = Inches(1)
        section.bottom_margin = Inches(1)
        section.left_margin = Inches(1)
        section.right_margin = Inches(1)
    
    # Título principal
    title_paragraph = doc.add_heading(f'Resumen: {title}', level=1)
    title_paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    
    doc.add_paragraph()  # Espacio
    
    # Parsear líneas
    lines = summary_content.split('\n')
    in_list = False
    
    for line in lines:
        line = line.strip()
        
        if not line:
            continue
        
        # Título H1 (ignorar porque ya pusimos título personalizado)
        if line.startswith('# ') and not line.startswith('## '):
            continue
        
        # Título H2
        elif line.startswith('## '):
            text = line[3:].strip()
            doc.add_heading(text, level=2)
            in_list = False
        
        # Título H3
        elif line.startswith('### '):
            text = line[4:].strip()
            doc.add_heading(text, level=3)
            in_list = False
        
        # Listas
        elif line.startswith('- ') or line.startswith('* '):
            text = line[2:].strip()
            # Limpiar emojis
            text = _clean_emoji_for_word(text)
            doc.add_paragraph(text, style='List Bullet')
            in_list = True
        
        # Texto normal
        else:
            # Limpiar markdown inline
            clean_text = _clean_markdown_for_word(line)
            if in_list:
                doc.add_paragraph()
                in_list = False
            paragraph = doc.add_paragraph(clean_text)
            paragraph.paragraph_format.space_after = Pt(6)
    
    # Guardar a bytes
    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


def _clean_emoji_for_word(text: str) -> str:
    """Limpia emojis para Word."""
    emoji_map = {
        '📋': '-',
        '🎯': '-',
        '❓': '?',
        '🔍': '-',
    }
    for emoji, replacement in emoji_map.items():
        text = text.replace(emoji, replacement)
    return text


def _clean_markdown_for_word(text: str) -> str:
    """Convierte markdown inline a formato Word."""
    # Negritas **texto** -> texto en negrita
    import re
    def replace_bold(match):
        return match.group(1)
    
    text = re.sub(r'\*\*(.*?)\*\*', r'\1', text)  # Word no soporta negritas inline fácilmente
    text = re.sub(r'\*(.*?)\*', r'\1', text)      # Itálicas
    return text