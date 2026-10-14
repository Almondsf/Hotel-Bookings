"""Render an issued invoice (from its frozen snapshot) as a PDF."""
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def _table(rows, widths, header=True):
    table = Table(rows, colWidths=widths, hAlign='LEFT')
    style = [
        ('FONTSIZE', (0, 0), (-1, -1), 8.5),
        ('ALIGN', (-1, 0), (-1, -1), 'RIGHT'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LINEBELOW', (0, -1), (-1, -1), 0.25, colors.grey),
    ]
    if header:
        style += [('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                  ('LINEBELOW', (0, 0), (-1, 0), 0.5, colors.black)]
    table.setStyle(TableStyle(style))
    return table


def render_invoice(invoice):
    snap = invoice.snapshot
    currency = snap['currency']
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=16 * mm, bottomMargin=16 * mm, title=f"Invoice {invoice.number}")
    styles = getSampleStyleSheet()
    story = []

    hotel = snap['hotel']
    story.append(Paragraph(f"<b>{escape(hotel['name'])}</b>", styles['Title']))
    details = ' · '.join(x for x in [hotel['address'], hotel['phone'], hotel['email']] if x)
    if details:
        story.append(Paragraph(escape(details), styles['Normal']))
    if hotel['tax_id']:
        story.append(Paragraph(f"TIN: {escape(hotel['tax_id'])}", styles['Normal']))
    story.append(Spacer(1, 8 * mm))

    bill_to = snap['bill_to']
    meta = [
        ['Invoice', invoice.number],
        ['Date', invoice.issued_at.strftime('%d %b %Y')],
        ['Folio', snap['folio']],
        ['Bill to', bill_to['name']],
    ]
    if bill_to.get('company_tax_id'):
        meta.append(['Company TIN', bill_to['company_tax_id']])
    if snap.get('stay'):
        stay = snap['stay']
        meta += [['Confirmation', stay['confirmation_number']], ['Room', stay['room']],
                 ['Stay', f"{stay['check_in_date']} to {stay['check_out_date']}"]]
    story.append(_table(meta, [35 * mm, 120 * mm], header=False))
    story.append(Spacer(1, 6 * mm))

    rows = [['Date', 'Description', 'Qty', 'Net', 'Tax', f'Total ({currency})']]
    rows += [[c['date'], Paragraph(escape(c['description']), styles['Normal']), c['quantity'], c['net'], c['tax'], c['total']]
             for c in snap['charges']]
    story.append(_table(rows, [22 * mm, 70 * mm, 12 * mm, 24 * mm, 22 * mm, 26 * mm]))
    story.append(Spacer(1, 4 * mm))

    if snap['taxes']:
        tax_rows = [['Tax', 'Rate', 'Amount']]
        tax_rows += [[t['name'], f"{float(t['rate']) * 100:.2f}%", t['amount']] for t in snap['taxes']]
        story.append(_table(tax_rows, [80 * mm, 30 * mm, 30 * mm]))
        story.append(Spacer(1, 4 * mm))

    if snap['payments']:
        pay_rows = [['Date', 'Payment', 'Reference', 'Amount']]
        pay_rows += [[p['date'], f"{p['method']}{' (refund)' if p['kind'] == 'REFUND' else ''}", p['reference'],
                      p['amount']] for p in snap['payments']]
        story.append(_table(pay_rows, [22 * mm, 60 * mm, 50 * mm, 26 * mm]))
        story.append(Spacer(1, 4 * mm))

    totals = snap['totals']
    story.append(_table([
        ['Net', totals['net']], ['Tax', totals['tax']], ['Total', totals['total']],
        ['Paid', totals['paid']], ['Balance due', totals['balance']],
    ], [130 * mm, 28 * mm], header=False))

    doc.build(story)
    return buffer.getvalue()
