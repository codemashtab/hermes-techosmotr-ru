import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from techosmotr import summarize

OK = {"status": "OK", "checks": [{"name": "config", "severity": "OK", "summary": "", "findings": []}]}
WARN = {"status": "WARN", "checks": [{"name": "config", "severity": "WARN", "summary": "", "findings": [
    {"id": "config.missing", "severity": "WARN", "component": "config", "summary": "Profile config.yaml is missing",
     "profile": "sales", "next_action": "Run hermes --profile sales config path"}]}]}

def test_ok():
    t, c = summarize(OK)
    assert c == 0 and "в порядке" in t

def test_warn():
    t, c = summarize(WARN)
    assert c == 1 and "Нет файла настроек" in t and "sales" in t
