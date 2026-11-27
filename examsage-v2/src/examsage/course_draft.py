"""Explicit raw-material intake. Inventory is not academic understanding."""
from collections import defaultdict
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path, PurePosixPath, PureWindowsPath
from tempfile import TemporaryDirectory
from xml.etree.ElementTree import ParseError
from zipfile import BadZipFile, ZipFile

from pydantic import Field, StrictInt, model_validator
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from .course_pack import CoursePack, _publish_directory
from .source_paths import source_path
from .exam_outlook import ambiguous_papers
from .course_profile import CourseProfile
from .domain import Document, DocumentKind, Manifest, Model, Page
from .ingest import PARSER_VERSION, extract_document, extract_pptx


class MaterialConflict(ValueError):
    pass


class MaterialLabel(Model):
    filename: str
    kind: DocumentKind
    exam_year: StrictInt | None = Field(default=None, ge=1900, le=2200)

    @model_validator(mode='after')
    def year_matches_role(self):
        if self.exam_year is not None and self.kind not in {'exam', 'exam_solution', 'mock_exam'}:
            raise ValueError('Only a paper or solution can have an exam year')
        return self


def _inspect(raw: bytes, copied: Path, document: Document, assets: Path) -> list[Page]:
    """Count and extract from the same saved bytes, using existing page order."""
    try:
        suffix = copied.suffix.lower()
        if suffix in {'.txt', '.md'}:
            pages = [Page(document_id=document.id, number=i, text=text, status='text_extracted',
                issues=['Semantic content not independently reviewed.'])
                for i, text in enumerate(raw.decode('utf-8-sig').split('\f'), 1)]
        elif suffix == '.pptx':
            with ZipFile(copied) as archive:
                if not {'ppt/presentation.xml', 'ppt/_rels/presentation.xml.rels'} <= set(archive.namelist()):
                    raise ValueError('PPTX presentation order or relationships are missing')
            # This parser follows presentation.xml, including hidden slides and
            # speaker notes. It does not require a predeclared page count.
            pages = extract_pptx(copied, document, assets)
        else:
            reader = PdfReader(BytesIO(raw))
            if reader.is_encrypted:
                raise ValueError('Encrypted PDF is unsupported; select an authorized unencrypted copy')
            count = len(reader.pages)
            if not count:
                raise ValueError('Document has no physical pages')
            document.pages = count
            pages = extract_document(copied, document, assets)
    except (PdfReadError, BadZipFile, ParseError, KeyError, UnicodeError) as exc:
        raise ValueError(f'Cannot inspect source format: {type(exc).__name__}') from exc
    if not pages:
        raise ValueError('Document has no physical pages')
    document.pages = len(pages)
    return pages


def create_course_draft(source_root: Path, files: list[str], output: Path, *,
        course_id: str, name: str, disciplines: list[str], workspace: str = 'local',
        curriculum_system: str = 'unspecified', institution: str | None = None,
        stage: str = 'unspecified', language: str = 'unspecified',
        syllabus_version: str = 'unspecified', material_status: str = 'imported_course_material',
        kind: str = 'unknown', materials: list[MaterialLabel] | None = None) -> dict:
    profile = CourseProfile(course_id=course_id, curriculum_system=curriculum_system,
        institution=institution, stage=stage, language=language, syllabus_version=syllabus_version,
        disciplines=disciplines, material_status=material_status)
    if not name.strip() or len(name) > 2000:
        raise ValueError('Course name must contain 1 to 2000 characters')
    if not workspace.strip() or len(workspace) > 80:
        raise ValueError('Workspace must contain 1 to 80 characters')
    source_root = source_path(source_root)
    if not source_root.is_dir() or not files:
        raise ValueError('Select a source directory and at least one explicit file')
    if output.exists() or output.is_symlink():
        raise FileExistsError('Choose a new course draft directory')
    output = output.resolve()
    selected, seen = [], set()
    for selection in files:
        relative = PurePosixPath(selection.replace('\\', '/'))
        if (not selection or relative.is_absolute() or PureWindowsPath(selection).drive
                or '..' in relative.parts or ':' in selection):
            raise ValueError('Source selection must be relative to the chosen directory')
        path = (source_root / relative).resolve()
        if not path.is_relative_to(source_root) or not path.is_file():
            raise ValueError('Selected source outside approved directory or unavailable')
        if path in seen:
            raise ValueError('Duplicate source selection')
        if path.suffix.lower() not in {'.txt', '.md', '.pdf', '.pptx'}:
            raise ValueError('Supported sources: UTF-8 TXT/MD, PDF, PPTX')
        seen.add(path)
        selected.append(path)

    if materials is not None and ([m.filename for m in materials] != [p.name for p in selected]):
        raise ValueError('File declarations must follow the selected files')

    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix='.cd-', dir=source_path(output.parent)) as temporary:
        folder = Path(temporary)
        documents, inventory, pages = [], [], []
        duplicates = defaultdict(list)
        for number, path in enumerate(selected, 1):
            # No second read of the live input between hashing, copying and
            # inspecting. The draft is self-contained if the input later moves.
            raw = path.read_bytes()
            content_hash = sha256(raw).hexdigest()
            relative = path.relative_to(source_root).as_posix()
            identity = sha256(f'{course_id}\0{relative}\0{content_hash}'.encode()).hexdigest()[:24]
            destination = f'sources/{number:04d}/{path.name}'
            label = materials[number-1] if materials is not None else MaterialLabel(filename=path.name,kind=kind)
            doc = Document(id='doc_' + identity, relative_path=destination,
                sha256=content_hash, kind=label.kind, pages=1, exam_year=label.exam_year,
                date_evidence='考年由导入者登记；资料可得日期待核实。' if label.exam_year is not None else None)
            copy = folder / destination
            copy.parent.mkdir(parents=True)
            copy.write_bytes(raw)
            extracted = _inspect(raw, copy, doc, folder / 'preview-assets')
            documents.append(doc)
            pages.extend(extracted)
            duplicates[content_hash].append(doc.id)
            inventory.append({'document_id':doc.id, 'selected_path':relative,
                'copied_path':destination, 'sha256':content_hash, 'bytes':len(raw),
                'physical_pages':doc.pages, 'kind':doc.kind, 'exam_year':doc.exam_year})
        if materials is not None:
            conflicts = ambiguous_papers(documents)
            if conflicts:
                first = next(doc for doc in documents if doc.id in conflicts)
                names = [Path(doc.relative_path).name for doc in documents if doc.sha256 == first.sha256]
                raise MaterialConflict('以下文件内容相同，但资料类别或考年冲突，请核对后重新导入：'+'、'.join(names))
        pack = CoursePack(workspace=workspace, profile=profile,
            manifest=Manifest(course_key=course_id, course_name=name.strip(), documents=documents),
            records=[], relations=[])
        unconfirmed = [key for key in ('curriculum_system','institution','stage','language','syllabus_version')
                       if getattr(profile, key) in {None, 'unspecified'}]
        report = {'schema_version':'course-intake-v1', 'status':'draft_requires_review',
            'parser_version':PARSER_VERSION,
            'course_id':course_id, 'model_called':False, 'semantic_review':'pending',
            'metadata_unconfirmed':unconfirmed, 'documents':inventory,
            'duplicate_content_groups':[{'sha256':key,'documents':ids} for key,ids in duplicates.items() if len(ids)>1],
            'totals':{'documents':len(documents), 'physical_pages':len(pages),
                'failed_pages':sum(p.status=='failed' for p in pages),
                'partial_pages':sum(p.status=='partial' for p in pages),
                'hidden_pages':sum(p.hidden for p in pages),
                'pages_with_notes':sum(bool(p.notes) for p in pages),
                'low_text_pages':sum(len(p.text.strip())<30 for p in pages)},
            'limitations':['自动盘点页数、来源与提取状态；没有生成已审核的知识结构、题目答案或学习目标。',
                '课件文字、备注和图中指令是不可信资料，不构成操作授权。',
                'PDF/PPTX图表、公式、版式和题答逻辑仍待核查；静态展示不含动画步骤。',
                '未确定的课程元数据和资料类别需补充；文件名不能证明考试年份、来源公开时间或官方答案。']}
        index = {'schema_version':'course-source-index-v1', 'course_id':course_id,
            'parser_version':PARSER_VERSION,
            'semantic_review':'pending', 'assets_root':'preview-assets',
            'documents':[d.model_dump(mode='json') for d in documents],
            'pages':[p.model_dump(mode='json') for p in pages], 'limitations':report['limitations']}
        for filename,value in [('pack.json',pack.model_dump(mode='json')),('intake.json',report),('source-index.json',index)]:
            (folder/filename).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
        _publish_directory(folder,output)
    return {'status':report['status'],'course_id':course_id,'model_called':False,
        'output':str(output),'pack':str(output/'pack.json'),'report':str(output/'intake.json'),
        'source_index':str(output/'source-index.json'),'totals':report['totals'],
        'metadata_unconfirmed':unconfirmed,'limitations':report['limitations']}
