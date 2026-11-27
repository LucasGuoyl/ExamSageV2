from pathlib import Path

import pytest

from examsage.course_pack import CoursePack, import_pack
from test_course_pack import pack_data


@pytest.mark.parametrize('failure', ['transient', 'persistent', 'target_appears', 'unrelated'])
def test_import_publication_handles_only_transient_windows_locks(tmp_path, monkeypatch, failure):
    source, output = tmp_path/'source', tmp_path/'output'
    pack = CoursePack.model_validate(pack_data(source))
    original, attempts = Path.rename, []
    def guarded_rename(path, target):
        if path.name != 'course': return original(path,target)
        attempts.append(path)
        if failure == 'target_appears' and len(attempts) == 1:
            output.mkdir()
            (output/'user-file.txt').write_text('preserve', encoding='utf-8')
        if len(attempts) == 1 or failure in {'persistent', 'unrelated'}:
            error = PermissionError('Synthetic OS error for publication test')
            error.winerror = 5 if failure != 'unrelated' else 87
            raise error
        return original(path,target)
    monkeypatch.setattr(Path, 'rename', guarded_rename)
    if failure == 'transient':
        import_pack(pack, source, output)
        assert (output/'course.sqlite3').is_file()
        assert len(attempts) == 2
    else:
        with pytest.raises(FileExistsError if failure == 'target_appears' else PermissionError):
            import_pack(pack, source, output)
        if failure == 'target_appears':
            assert list(output.iterdir()) == [output/'user-file.txt']
            assert (output/'user-file.txt').read_text(encoding='utf-8') == 'preserve'
            assert len(attempts) == 1
        else:
            assert not output.exists()
            assert len(attempts) == (4 if failure == 'persistent' else 1)
    assert not list(tmp_path.glob('.course-import-*'))
