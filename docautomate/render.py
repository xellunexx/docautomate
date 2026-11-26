"""Word template checking, filling and PDF conversion."""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import jinja2
from jinja2 import nodes
from docxtpl import DocxTemplate

from .context import PLACEHOLDERS, sample_context

TOP_LEVEL = {"candidate", "employer", "position", "case", "today"}
_XML_PARTS = ("word/document.xml", "word/header", "word/footer")


def _jinja_env() -> jinja2.Environment:
    # StrictUndefined: a misspelled tag fails loudly instead of printing nothing.
    return jinja2.Environment(undefined=jinja2.StrictUndefined, autoescape=True)


@dataclass
class TemplateCheck:
    ok: bool
    used: set[str] = field(default_factory=set)       # dotted placeholders used
    unknown: list[str] = field(default_factory=list)  # not in PLACEHOLDERS
    errors: list[str] = field(default_factory=list)


def _template_sources(tpl: DocxTemplate) -> list[str]:
    tpl.init_docx()
    out = []
    for part in tpl.docx.part.package.iter_parts():
        name = str(part.partname).lstrip("/")
        if name.startswith(_XML_PARTS) and name.endswith(".xml"):
            out.append(tpl.patch_xml(part.blob.decode("utf-8")))
    return out


def _collect(ast: nodes.Template) -> tuple[set[str], set[str]]:
    """Return (dotted names like 'candidate.name_cyr', bare top-level names)."""
    dotted, bare = set(), set()
    assigned = {n.name for n in ast.find_all(nodes.Name) if n.ctx in ("store", "param")}
    for n in ast.find_all(nodes.Getattr):
        if isinstance(n.node, nodes.Name) and n.node.name in TOP_LEVEL - {"today"}:
            dotted.add(f"{n.node.name}.{n.attr}")
    for n in ast.find_all(nodes.Getitem):
        if isinstance(n.node, nodes.Name) and isinstance(n.arg, nodes.Const) and n.node.name in TOP_LEVEL:
            dotted.add(f"{n.node.name}.{n.arg.value}")
    for n in ast.find_all(nodes.Name):
        if n.ctx == "load" and n.name not in assigned:
            bare.add(n.name)
    return dotted, bare


def check_template(path: Path) -> TemplateCheck:
    """Find every {{ tag }} in a .docx, report unknown or broken ones, and try a test fill."""
    res = TemplateCheck(ok=False)
    try:
        tpl = DocxTemplate(str(path))
        sources = _template_sources(tpl)
    except Exception as exc:  # not a docx, corrupted zip, …
        res.errors.append(f"Файлът не може да се отвори като Word (.docx): {exc}")
        return res

    env = _jinja_env()
    for src in sources:
        try:
            ast = env.parse(src)
        except jinja2.TemplateSyntaxError as exc:
            res.errors.append(f"Грешно поле или условие около: „{_snippet(src, exc.lineno)}“ – {exc.message}")
            continue
        dotted, bare = _collect(ast)
        res.used |= dotted
        for name in bare - TOP_LEVEL:
            res.unknown.append(name)
        if "today" in bare:
            res.used.add("today")
    res.unknown += sorted(k for k in res.used if k not in PLACEHOLDERS)
    res.unknown = sorted(set(res.unknown))
    res.used = {k for k in res.used if k in PLACEHOLDERS}

    if not res.errors and not res.unknown:
        try:
            with tempfile.TemporaryDirectory() as tmp:
                fill_docx(path, sample_context(), Path(tmp) / "test.docx")
        except Exception as exc:
            res.errors.append(f"Пробното попълване не успя: {exc}")
    res.ok = not res.errors and not res.unknown
    return res


def _snippet(src: str, lineno: int | None) -> str:
    import re
    text = re.sub(r"<[^>]+>", "", src)
    lines = text.splitlines() or [text]
    line = lines[min(max((lineno or 1) - 1, 0), len(lines) - 1)]
    i = line.find("{")
    return (line[max(i - 20, 0): i + 60] if i >= 0 else line[:80]).strip()


def fill_docx(template: Path, ctx: dict, out: Path) -> Path:
    tpl = DocxTemplate(str(template))
    tpl.render(ctx, jinja_env=_jinja_env(), autoescape=True)
    out.parent.mkdir(parents=True, exist_ok=True)
    tpl.save(str(out))
    return out


# ---------------------------------------------------------------- PDF

class PdfConverterMissing(RuntimeError):
    pass


def find_soffice() -> str | None:
    env = os.environ.get("DOCAUTOMATE_SOFFICE")
    if env and Path(env).exists():
        return env
    for name in ("soffice", "libreoffice"):
        p = shutil.which(name)
        if p:
            return p
    if platform.system() == "Windows":
        for base in (os.environ.get("ProgramFiles", r"C:\Program Files"),
                     os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")):
            p = Path(base) / "LibreOffice" / "program" / "soffice.exe"
            if p.exists():
                return str(p)
    return None


def _word_available() -> bool:
    if platform.system() != "Windows":
        return False
    try:
        import win32com.client  # noqa: F401  (pywin32)
        return True
    except ImportError:
        return False


def converter_name() -> str | None:
    if find_soffice():
        return "LibreOffice"
    if _word_available():
        return "Microsoft Word"
    return None


def to_pdf(docx_files: list[Path], outdir: Path) -> dict[Path, Path]:
    """Convert .docx files to PDF. Returns {docx: pdf}. Raises PdfConverterMissing."""
    outdir.mkdir(parents=True, exist_ok=True)
    soffice = find_soffice()
    result: dict[Path, Path] = {}
    if soffice:
        with tempfile.TemporaryDirectory() as profile:
            cmd = [soffice, f"-env:UserInstallation={Path(profile).as_uri()}", "--headless",
                   "--convert-to", "pdf", "--outdir", str(outdir), *map(str, docx_files)]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        for f in docx_files:
            pdf = outdir / (f.stem + ".pdf")
            if pdf.exists():
                result[f] = pdf
        if len(result) != len(docx_files):
            missing = [f.name for f in docx_files if f not in result]
            raise RuntimeError(f"LibreOffice не създаде PDF за: {', '.join(missing)}. {proc.stderr[-500:]}")
        return result
    if _word_available():
        import pythoncom
        import win32com.client
        pythoncom.CoInitialize()
        word = win32com.client.DispatchEx("Word.Application")
        word.Visible = False
        try:
            for f in docx_files:
                pdf = outdir / (f.stem + ".pdf")
                doc = word.Documents.Open(str(f.resolve()), ReadOnly=True)
                try:
                    doc.SaveAs2(str(pdf.resolve()), FileFormat=17)  # wdFormatPDF
                finally:
                    doc.Close(False)
                result[f] = pdf
        finally:
            word.Quit()
        return result
    raise PdfConverterMissing(
        "Няма програма за PDF. Инсталирайте LibreOffice (безплатно) или Microsoft Word с pywin32."
    )
