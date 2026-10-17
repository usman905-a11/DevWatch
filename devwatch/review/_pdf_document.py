"""Private document layout used only by accepted renderers and their worker."""
from html import escape
from io import BytesIO
from pathlib import Path
import unicodedata
import re
from threading import Lock

import reportlab
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate

_FONT = "DevWatchVera"
pdfmetrics.registerFont(TTFont(_FONT, str(Path(reportlab.__file__).parent / "fonts" / "Vera.ttf")))
_GLYPHS = pdfmetrics.getFont(_FONT).face.charToGlyph
_BUILD_LOCK = Lock()


def _literal(value: str) -> str:
    # The bundled font avoids host-font/network dependencies. Unsupported glyphs
    # and invisible controls are represented losslessly rather than as squares.
    text = "".join(char if char == "\n" or (ord(char) in _GLYPHS
        and unicodedata.category(char) not in {"Cc", "Cf", "Cs"}
        and char not in "\u2010\u2011\u2012\u2013\u2014\u2015")
        else char.encode("unicode_escape").decode("ascii") for char in value)
    literal = escape(text, quote=False).replace("\n", "<br/>")
    return re.sub(r" {2,}", lambda match: "&#160;" * len(match[0]), literal)


def render_document(draft: dict) -> bytes:
    # TTFont's font-face reader has mutable seek state. Protect complete builds
    # for direct synchronous callers; runtime workers each have their own font.
    with _BUILD_LOCK:
        return _build_document(draft)


def _build_document(draft: dict) -> bytes:
    body = ParagraphStyle("body", fontName=_FONT, fontSize=9.5, leading=14,
                          textColor=HexColor("#253343"), spaceAfter=7, splitLongWords=1)
    title = ParagraphStyle("title", parent=body, fontSize=23, leading=29, spaceAfter=14, keepWithNext=True)
    heading = ParagraphStyle("heading", parent=body, fontSize=14, leading=20, spaceBefore=14,
                             spaceAfter=8, textColor=HexColor("#163d62"), keepWithNext=True)
    subheading = ParagraphStyle("subheading", parent=body, fontSize=11, leading=16,
                                spaceBefore=8, keepWithNext=True)
    story = []
    def add(value, style=body):
        story.append(Paragraph(_literal(value), style))
    add("DevWatch review", title)
    add("Snapshot: " + draft["snapshot_id"])
    add(draft["summary"])
    add("Read-only review. Remediation is guidance; reviewed source is unchanged.")
    add("Glyphs outside the bundled font and invisible controls appear as Unicode escapes.")
    for label, findings in (("Confirmed defects", draft["confirmed_defects"]),
                            ("Uncertain high-impact candidates", draft["uncertain_high_impact_candidates"]),
                            ("Advisories", draft["advisories"])):
        add(f"{label} ({len(findings)})", heading)
        if not findings:
            add("None reported.")
        for finding in sorted(findings, key=lambda item: (item["location"]["file_path"], item["location"]["start_line"], item["finding_id"])):
            location = finding["location"]
            add(finding["title"], subheading)
            add(f"Location: {location['file_path']}:{location['start_line']}-{location['end_line']}")
            for field, value in (("Description", finding["description"]), ("Impact", finding["impact"]),
                                 ("Evidence", ", ".join(finding["evidence_refs"])),
                                 ("Verification", finding["verification_rationale"]),
                                 ("Confidence", f"{finding['confidence']:.2f}"), ("Remediation", finding["remediation"])):
                add(f"{field}: {value}")
    add("Coverage", heading)
    coverage = draft["coverage"]
    add(f"Files inspected: {len(coverage['inspected_files'])}; symbols inspected: {len(coverage['inspected_symbols'])}")
    for label, items in (("Inspected files", coverage["inspected_files"]),
                         ("Inspected symbols", coverage["inspected_symbols"])):
        add(label, subheading)
        for item in sorted(items):
            add("- " + item)
        if not items:
            add("None recorded.")
    for label, items in (("Skipped", coverage["skipped"]), ("Failed", coverage["failed"])):
        add(f"{label} ({len(items)})", subheading)
        for path, reason in sorted(items.items()):
            add(f"- {path}: {reason}")
        if not items:
            add("None recorded.")
    add("Limitations", heading)
    limitations = sorted(set(draft["limitations"] + coverage["limitations"]))
    for item in limitations:
        add("- " + item)
    if not limitations:
        add("None recorded.")
    def footer(canvas, document):
        canvas.saveState()
        canvas.setFont(_FONT, 8)
        canvas.setFillColor(HexColor("#526474"))
        canvas.drawString(42, 28, "DevWatch | Accepted review")
        canvas.drawRightString(A4[0] - 42, 28, f"Page {document.page}")
        canvas.restoreState()
    output = BytesIO()
    document = SimpleDocTemplate(output, pagesize=A4, leftMargin=42, rightMargin=42,
        topMargin=42, bottomMargin=48, invariant=1, pageCompression=1,
        title="DevWatch review", author="DevWatch")
    document.build(story, onFirstPage=footer, onLaterPages=footer)
    return output.getvalue()
