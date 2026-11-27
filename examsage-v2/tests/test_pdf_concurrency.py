from concurrent.futures import ThreadPoolExecutor
from threading import Lock
import time
from PIL import Image

def test_parallel_previews_never_enter_pdfium_together(tmp_path,monkeypatch):
    import pypdfium2
    from examsage.ingest import render_pdf_page
    active=0;guard=Lock()
    class Bitmap:
        def to_pil(self):return Image.new('RGB',(20,20))
        def close(self):pass
    class Page:
        def render(self,scale):return Bitmap()
        def close(self):pass
    class Document:
        def __init__(self,path):
            nonlocal active
            with guard:
                assert active==0,'PDFium called concurrently'
                active+=1
        def __enter__(self):time.sleep(.02);return self
        def __exit__(self,*args):
            nonlocal active
            with guard:active-=1
        def __len__(self):return 1
        def __getitem__(self,n):return Page()
    monkeypatch.setattr(pypdfium2,'PdfDocument',Document)
    with ThreadPoolExecutor(max_workers=6) as pool:
        paths=list(pool.map(lambda n:render_pdf_page(tmp_path/'source.pdf',1,tmp_path/f'{n}.png'),range(12)))
    for path in paths:
        with Image.open(path) as image:image.verify()
    assert not list(tmp_path.glob('*.tmp'))

def test_failed_render_does_not_publish_partial_preview(tmp_path,monkeypatch):
    import pytest
    import pypdfium2
    from examsage.ingest import render_pdf_page
    class Broken:
        def __init__(self,*args):raise RuntimeError('render failed')
    monkeypatch.setattr(pypdfium2,'PdfDocument',Broken)
    output=tmp_path/'broken.png'
    with pytest.raises(RuntimeError):render_pdf_page(tmp_path/'source.pdf',1,output)
    assert not output.exists()
