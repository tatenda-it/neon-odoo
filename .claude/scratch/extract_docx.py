"""Extract .docx as plain text. Stdlib only.

Reads `word/document.xml` and the numbering/styles XML to flatten
paragraphs into newline-delimited text, marking headings with
"## " / "### " prefixes.

Usage: python extract_docx.py <input.docx> <output.txt>
"""
import io
import sys
import zipfile
from xml.etree import ElementTree as ET

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W_NS}


def _para_text(p):
    runs = []
    for t in p.iter(f"{{{W_NS}}}t"):
        runs.append(t.text or "")
    # also handle line breaks within a run
    return "".join(runs)


def _para_style(p):
    pPr = p.find("w:pPr", NS)
    if pPr is None:
        return ""
    pStyle = pPr.find("w:pStyle", NS)
    if pStyle is None:
        return ""
    return pStyle.get(f"{{{W_NS}}}val", "") or ""


def extract(src):
    with zipfile.ZipFile(src) as z:
        xml = z.read("word/document.xml")
    root = ET.fromstring(xml)
    out = []
    for p in root.iter(f"{{{W_NS}}}p"):
        style = _para_style(p)
        text = _para_text(p).rstrip()
        if not text and not style:
            out.append("")
            continue
        if style.lower().startswith("title"):
            out.append("# " + text)
        elif style.startswith("Heading1") or style == "Heading 1":
            out.append("## " + text)
        elif style.startswith("Heading2") or style == "Heading 2":
            out.append("### " + text)
        elif style.startswith("Heading"):
            # generic heading levels 3+
            out.append("#### " + text)
        else:
            out.append(text)
    return "\n".join(out)


if __name__ == "__main__":
    src, dst = sys.argv[1], sys.argv[2]
    text = extract(src)
    with open(dst, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    print(f"{src} -> {dst} ({len(text)} chars, {text.count(chr(10))} newlines)")
