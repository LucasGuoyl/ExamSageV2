from __future__ import annotations

from hashlib import sha256
from pathlib import Path, PurePosixPath
from zipfile import ZipFile
from xml.etree import ElementTree as ET
import json
import logging
import posixpath
import re
import shutil
import uuid
from threading import RLock

from .domain import Document, Manifest, Page, Record, SourceRef, digest

PARSER_VERSION = "native-layout-v2.3"
PDFIUM_LOCK = RLock()  # PDFium forbids simultaneous calls even for different PDFs.
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
P = "http://schemas.openxmlformats.org/presentationml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def atomic_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    temp.replace(path)


def safe_member(base: str, target: str) -> str:
    target = target.replace("\\", "/")
    if ":" in target or target.startswith("/"):
        raise ValueError("external/archive absolute target")
    result = posixpath.normpath(posixpath.join(posixpath.dirname(base), target))
    if result == ".." or result.startswith("../"):
        raise ValueError("archive traversal")
    return result


def xml(z: ZipFile, name: str):
    if z.getinfo(name).file_size > 32_000_000:
        raise ValueError("XML entry exceeds size limit")
    content = z.read(name)
    if b"<!DOCTYPE" in content or b"<!ENTITY" in content:
        raise ValueError("XML entity declarations are unsupported")
    return ET.fromstring(content)


def relationships(z, part):
    name = str(PurePosixPath(part).parent / "_rels" / (PurePosixPath(part).name + ".rels"))
    if name not in z.namelist():
        return {}
    return {e.attrib["Id"]: (safe_member(part, e.attrib["Target"]), e.attrib.get("Type", ""))
            for e in xml(z, name) if e.attrib.get("TargetMode") != "External"}


def paragraphs(root):
    # Preserve text runs within a paragraph, including separate superscript runs.
    return "\n".join("".join(p.itertext()) if p.tag == f"{{{A}}}t" else
                     "".join(t.text or "" for t in p.iter(f"{{{A}}}t"))
                     for p in root.iter(f"{{{A}}}p")).strip()


def extract_pptx(path: Path, doc: Document, assets: Path) -> list[Page]:
    pages = []
    with ZipFile(path) as z:
        if sum(x.file_size for x in z.infolist()) > 1_000_000_000:
            raise ValueError("archive expanded size limit exceeded")
        parts = sorted((n for n in z.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)), key=lambda n: int(re.search(r"slide(\d+)", n)[1]))
        if "ppt/presentation.xml" in z.namelist():
            rels = relationships(z, "ppt/presentation.xml")
            parts = [rels[e.attrib[f"{{{R}}}id"]][0] for e in xml(z, "ppt/presentation.xml").iter(f"{{{P}}}sldId")]
        for number, part in enumerate(parts, 1):
            root = xml(z, part)
            shown = root.attrib.get('show', '1')
            if shown not in {'0', '1', 'false', 'true'}:
                raise ValueError('Invalid slide visibility')
            rels = relationships(z, part)
            notes = []
            for target, kind in rels.values():
                if kind.endswith("/notesSlide"):
                    note_root = xml(z, target)
                    for shape in note_root.iter(f"{{{P}}}sp"):
                        placeholder = shape.find(f".//{{{P}}}ph")
                        if placeholder is None or placeholder.attrib.get("type", "body") == "body":
                            notes.append(paragraphs(shape))
            media = []
            for blip in root.iter(f"{{{A}}}blip"):
                rid = blip.attrib.get(f"{{{R}}}embed")
                if rid not in rels:
                    continue
                member = rels[rid][0]
                if z.getinfo(member).file_size > 50_000_000:
                    continue
                data = z.read(member)
                suffix = PurePosixPath(member).suffix.lower()
                name = f"media/{sha256(data).hexdigest()}{suffix}"
                destination = assets / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                if not destination.exists():
                    destination.write_bytes(data)
                media.append(name)
            text = paragraphs(root)
            issues = ["visual_layout_not_verified", "embedded_equations_may_require_visual_review"]
            if len(text.strip()) < 30:
                issues.append("little_or_no_native_text")
            pages.append(Page(document_id=doc.id, number=number, text=text, notes="\n".join(notes),
                              hidden=shown in {'0', 'false'}, image_count=len(media),
                              assets=sorted(set(media)), issues=issues, status="partial"))
    return pages


def only_replacement_characters(text: str) -> bool:
    return "\ufffd" in text and not text.replace("\ufffd", "").strip()


def extract_document(path: Path, doc: Document, assets: Path) -> list[Page]:
    assets.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".pptx":
        pages = extract_pptx(path, doc, assets)
    elif path.suffix.lower() == ".pdf":
        from pypdf import PdfReader
        logging.getLogger("pypdf").setLevel(logging.ERROR)
        pages = []
        reader = PdfReader(path)
        for number, page in enumerate(reader.pages, 1):
            issues = ["page_visuals_not_verified"]
            try:
                image_count = len(page.images)
            except Exception as exc:
                image_count = None
                issues.append("image_inventory_failed:" + type(exc).__name__)
            try:
                text = page.extract_text() or ""
                if only_replacement_characters(text):
                    raise UnicodeError("PDF text contains only undecodable characters")
                if len(text.strip()) < 30:
                    issues.append("little_or_no_native_text")
                pages.append(Page(document_id=doc.id, number=number, text=text,
                                  status="partial", image_count=image_count, issues=issues))
            except Exception as exc:
                pages.append(Page(document_id=doc.id, number=number, text="", status="failed",
                                  image_count=image_count,
                                  issues=issues+["native_extraction_failed:" + type(exc).__name__]))
    else:
        raise ValueError("Only PDF and PPTX are supported in phase one")
    if len(pages) != doc.pages:
        raise ValueError(f"Audited page count mismatch: {doc.relative_path}")
    return pages


def page_records(pages: list[Page], doc: Document) -> list[Record]:
    records = []
    for page in pages:
        ref = SourceRef(document_id=doc.id, page=page.number)
        title = next((x.strip() for x in page.text.splitlines() if x.strip()), Path(doc.relative_path).stem)[:180]
        reviewed = page.visual_review
        text = page.text
        if page.supplement:
            from .supplements import supplemental_text
            text += supplemental_text(page.supplement)
        if reviewed:
            text += '\n[原页核查导读 · 非官方答案]\n' + reviewed['summary']
            text += ''.join('\n\\(' + formula + '\\)' for formula in reviewed.get('formulas', []))
            text += ''.join('\n核查注记：' + note for note in reviewed.get('warnings', []))
        # Whole pages preserve formula conditions and layout context; retrieval can fetch adjacent pages.
        records.append(Record(id=f"{doc.id}:p{page.number}", kind="block", title=title,
                              text=text, refs=[ref], visibility="hidden" if page.hidden else "visible",
                              aliases=(page.supplement or {}).get('audit',{}).get('aliases',[]),
                              review="candidate" if page.status == "failed" else "machine_checked",
                              details={"raw_text": page.text, "source_kind": doc.kind,
                              "extraction_status": page.status, "image_count": page.image_count,
                              "assets": page.assets + ([page.render['asset']] if page.render else []),
                              "render": page.render, "visual_review": reviewed, "supplement":page.supplement,
                              "parser": PARSER_VERSION, "visual_status": page.visual_status},
                              limitations=page.issues))
        if page.notes:
            records.append(Record(id=f"{doc.id}:p{page.number}:notes", kind="block", title=title + " (speaker notes)",
                                  text=page.notes, refs=[ref], visibility="notes", review="machine_checked"))
    return records


def ingest(source_root: Path, manifest: Manifest, data_dir: Path) -> dict:
    assets = data_dir / "assets"
    pages, records = [], []
    processed = cached = 0
    for doc in manifest.documents:
        source = (source_root / doc.relative_path).resolve()
        if not source.is_relative_to(source_root.resolve()):
            raise ValueError("source escapes approved root")
        if sha256(source.read_bytes()).hexdigest() != doc.sha256:
            raise ValueError(f"Source changed: {doc.relative_path}")
        doc.asset = f"sources/{doc.sha256}{source.suffix.lower()}"
        destination = assets / doc.asset
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists():
            shutil.copyfile(source, destination)
        elif sha256(destination.read_bytes()).hexdigest() != doc.sha256:
            raise ValueError("Immutable source copy corrupted")
        cache = data_dir / "cache" / (digest([doc.id, doc.sha256, PARSER_VERSION]) + ".json")
        if cache.exists():
            extracted = [Page.model_validate(p) for p in json.loads(cache.read_text(encoding="utf-8"))]
            if any(p.status == "failed" or (source.suffix.lower() == ".pdf" and only_replacement_characters(p.text))
                   for p in extracted):
                extracted = extract_document(destination, doc, assets)
                atomic_json(cache, [p.model_dump() for p in extracted])
                processed += 1
            else:
                cached += 1
        else:
            extracted = extract_document(destination, doc, assets)
            atomic_json(cache, [p.model_dump() for p in extracted])
            processed += 1
        if source.suffix.lower() == '.pptx':
            from .slides import attach_slide_renders
            extracted = attach_slide_renders(doc, extracted, data_dir / 'slide-renders' / doc.sha256, assets)
        from .supplements import apply_supplements
        extracted = apply_supplements(doc, extracted, data_dir / 'page-supplements', assets)
        pages.extend(extracted)
        records.extend(page_records(extracted, doc))
    atomic_json(data_dir / "manifest.json", manifest.model_dump(mode="json"))
    return {"pages": pages, "records": records, "processed": processed, "cached": cached}


def render_pdf_page(source: Path, page: int, output: Path) -> Path:
    import pypdfium2 as pdfium
    from PIL import Image
    output.parent.mkdir(parents=True, exist_ok=True)
    with PDFIUM_LOCK:
        if output.exists():
            try:
                with Image.open(output) as cached:cached.verify()
                return output
            except (OSError,ValueError,SyntaxError):pass
        temp=output.with_name(output.name+'.'+uuid.uuid4().hex+'.tmp')
        try:
            with pdfium.PdfDocument(source) as pdf:
                if not 1 <= page <= len(pdf):raise ValueError('page out of range')
                p=pdf[page-1]
                try:
                    bitmap=p.render(scale=1.5)
                    try:bitmap.to_pil().save(temp,format='PNG')
                    finally:bitmap.close()
                finally:p.close()
            temp.replace(output)
        finally:
            if temp.exists():temp.unlink()
    return output
