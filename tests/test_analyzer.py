from pathlib import Path
from app.analyzer import parse_workbook, analyze

def test_sample_schedule():
    p=Path('data/sample_schedule.xlsx')
    task, rel=parse_workbook(p.read_bytes())
    result=analyze(task, rel)
    assert result['summary']['activities'] == 97
    assert result['summary']['relationships'] == 80
    assert result['summary']['schedule_health'] >= 0
