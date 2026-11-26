"""Dedicated, local PDF rendering for account briefs."""

from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib.pagesizes import A4
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from backend.services.pdf_export_service import _band_table, _build_styles, _fmt_date, _grid_table


def render_account_brief_pdf(brief):
    styles = _build_styles()
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=40, rightMargin=40,
                            topMargin=40, bottomMargin=40)
    story = []
    # Markdown is generated exclusively by the server; undo its escaping for PDF text.
    import re

    def clean(line):
        return re.sub(r'\\([\\`*_#\[\]<>])', r'\1', line)

    def paragraph(line, style='Body'):
        return Paragraph(escape(clean(line)), styles[style])

    _ = (_band_table, _fmt_date)  # Shared assessment layout helpers.
    sections = brief['markdown'].split('\n## ')
    first = sections[0].splitlines()
    story.append(paragraph(first[0].removeprefix('# '), 'Title'))
    for line in first[1:]:
        if line:
            story.append(paragraph(line, 'Subtitle'))
    table_sections = {'Technology inventory', 'Vendor-reported pipeline',
                      'Renewals (vendor-reported end dates)', 'Contacts & buying coverage', 'Open tasks'}
    for chunk in sections[1:]:
        heading, *content = chunk.splitlines()
        story.append(paragraph(heading, 'SectionHeader'))
        content = [line for line in content if line]
        if heading in table_sections and content and content != ['- Not recorded.']:
            rows = [[paragraph(line.removeprefix('- '))] for line in content]
            story.append(_grid_table(['Recorded evidence'], rows, [doc.width], align_center_from=1))
        else:
            story.extend(paragraph(line, 'Bullet') for line in content)
        story.append(Spacer(1, 4))
    doc.build(story)
    return buffer.getvalue()
