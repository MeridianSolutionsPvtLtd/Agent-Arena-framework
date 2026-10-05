import io
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
import re
import html

def _format_markdown_inline(text: str) -> str:
    """
    Escapes HTML/XML special characters and converts simple markdown 
    inline styles (**bold**, *italic*) to ReportLab-compatible tags.
    """
    # Escape special XML chars first to avoid breaking ReportLab's parser
    text = html.escape(text)
    
    # Bold: **text** or __text__ -> <b>text</b>
    text = re.sub(r'(\*\*|__)(.*?)\1', r'<b>\2</b>', text)
    
    # Italic: *text* or _text_ -> <i>text</i>
    text = re.sub(r'(\*|_)(.*?)\1', r'<i>\2</i>', text)
    
    return text

def generate_pdf_from_text(text: str) -> bytes:
    """Converts plain text or markdown-style text into a PDF and returns the bytes."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=72, leftMargin=72, topMargin=72, bottomMargin=72)
    
    styles = getSampleStyleSheet()
    
    # Custom styles
    title_style = ParagraphStyle(
        'TitleStyle',
        parent=styles['Heading1'],
        fontSize=18,
        spaceAfter=12,
        alignment=1, # Center
        textColor=colors.HexColor("#2E3E4E")
    )
    
    normal_style = styles['Normal']
    normal_style.fontSize = 11
    normal_style.leading = 14
    normal_style.spaceAfter = 10
    
    content = []
    
    # Simple line-by-line processing for title and paragraphs
    lines = text.split('\n')
    
    for i, line in enumerate(lines):
        line = line.strip()
        if not line:
            content.append(Spacer(1, 6))
            continue
        
        # Apply inline formatting to the line
        formatted_line = _format_markdown_inline(line)
        
        # Simple markdown detection for headings
        if line.startswith('### '):
            content.append(Paragraph(_format_markdown_inline(line[4:]), styles['Heading3']))
        elif line.startswith('## '):
            content.append(Paragraph(_format_markdown_inline(line[3:]), styles['Heading2']))
        elif line.startswith('# '):
            content.append(Paragraph(_format_markdown_inline(line[2:]), title_style))
        else:
            # Handle bullet points
            if line.startswith('- ') or line.startswith('* '):
                content.append(Paragraph(f"• {_format_markdown_inline(line[2:])}", normal_style))
            else:
                content.append(Paragraph(formatted_line, normal_style))
    
    doc.build(content)
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes
