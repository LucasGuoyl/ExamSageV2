"""A QA command must fail its exit status when a recorded check fails."""
import importlib.util
from pathlib import Path
import pytest


def test_data_audit_fails_for_any_recorded_failure():
    path=Path(__file__).resolve().parents[1]/'tools/comprehensive_qa.py'
    spec=importlib.util.spec_from_file_location('comprehensive_qa',path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with pytest.raises(SystemExit) as error:
        module.require_success([{'passed':True},{'passed':False}])
    assert error.value.code==1
    module.require_success([{'passed':True}])
