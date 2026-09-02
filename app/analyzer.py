from __future__ import annotations
import io
from typing import Any
import pandas as pd

TASK_COLUMNS = {
    'task_code': 'activity_id',
    'wbs_id': 'wbs',
    'task_name': 'activity_name',
    'target_drtn_hr_cnt': 'original_duration',
    'start_date': 'start',
    'end_date': 'finish',
    'remain_drtn_hr_cnt': 'remaining_duration',
    'pred_list': 'predecessors',
    'succ_list': 'successors',
    'total_float_hr_cnt': 'total_float',
    'status_code': 'status',
}

def _clean_sheet(df: pd.DataFrame, id_col: str) -> pd.DataFrame:
    if df.empty:
        return df
    # P6 Excel export contains a second human-readable header row.
    if str(df.iloc[0].get(id_col, '')).strip().lower() in {'activity id', 'predecessor'}:
        df = df.iloc[1:].copy()
    return df.reset_index(drop=True)

def parse_workbook(content: bytes) -> tuple[pd.DataFrame, pd.DataFrame]:
    book = pd.ExcelFile(io.BytesIO(content))
    if 'TASK' not in book.sheet_names or 'TASKPRED' not in book.sheet_names:
        raise ValueError('Workbook must contain TASK and TASKPRED sheets.')
    task = _clean_sheet(pd.read_excel(book, 'TASK'), 'task_code')
    rel = _clean_sheet(pd.read_excel(book, 'TASKPRED'), 'pred_task_id')
    return task, rel

def analyze(task: pd.DataFrame, rel: pd.DataFrame) -> dict[str, Any]:
    for col in ['target_drtn_hr_cnt', 'remain_drtn_hr_cnt', 'total_float_hr_cnt']:
        if col in task:
            task[col] = pd.to_numeric(task[col], errors='coerce')
    if 'lag_hr_cnt' in rel:
        rel['lag_hr_cnt'] = pd.to_numeric(rel['lag_hr_cnt'], errors='coerce')
    for col in ['start_date', 'end_date']:
        if col in task:
            task[col] = pd.to_datetime(task[col], errors='coerce')

    activity_ids = set(task['task_code'].dropna().astype(str))
    pred_ids = set(rel['pred_task_id'].dropna().astype(str))
    succ_ids = set(rel['task_id'].dropna().astype(str))
    no_pred = sorted(activity_ids - succ_ids)
    no_succ = sorted(activity_ids - pred_ids)

    tf = task['total_float_hr_cnt']
    duration = task['target_drtn_hr_cnt']
    lag = rel['lag_hr_cnt']
    statuses = task['status_code'].fillna('').astype(str).str.lower()

    issues = []
    if no_pred:
        issues.append({'severity': 'warning', 'type': 'OPEN_START', 'count': len(no_pred), 'message': 'Activities without predecessor'})
    if no_succ:
        issues.append({'severity': 'warning', 'type': 'OPEN_FINISH', 'count': len(no_succ), 'message': 'Activities without successor'})
    if (lag < 0).any():
        issues.append({'severity': 'critical', 'type': 'LEAD', 'count': int((lag < 0).sum()), 'message': 'Negative lags detected'})
    if (lag > 10).any():
        issues.append({'severity': 'warning', 'type': 'LONG_LAG', 'count': int((lag > 10).sum()), 'message': 'Relationships with lag > 10 days'})
    if (duration > 60).any():
        issues.append({'severity': 'warning', 'type': 'LONG_DURATION', 'count': int((duration > 60).sum()), 'message': 'Activities longer than 60 days'})
    if (tf < 0).any():
        issues.append({'severity': 'critical', 'type': 'NEGATIVE_FLOAT', 'count': int((tf < 0).sum()), 'message': 'Negative float activities'})

    # Transparent MVP health score; weights can be calibrated later.
    score = 100
    score -= min(15, len(no_pred) * 0.5)
    score -= min(15, len(no_succ) * 0.35)
    score -= min(15, int((lag < 0).sum()) * 5)
    score -= min(10, int((lag > 10).sum()) * 1)
    score -= min(15, int((duration > 60).sum()) * 0.15)
    score -= min(20, int((tf < 0).sum()) * 4)
    score = max(0, round(score, 1))

    cols = [c for c in TASK_COLUMNS if c in task.columns]
    activities = task[cols].rename(columns=TASK_COLUMNS).copy()
    for c in ['start', 'finish']:
        if c in activities:
            activities[c] = activities[c].dt.strftime('%Y-%m-%d').fillna('')
    activities = activities.replace({pd.NA: None, float('nan'): None})

    return {
        'summary': {
            'activities': int(len(task)),
            'relationships': int(len(rel)),
            'critical': int((tf <= 0).sum()),
            'near_critical': int(((tf > 0) & (tf <= 10)).sum()),
            'negative_float': int((tf < 0).sum()),
            'open_start': len(no_pred),
            'open_finish': len(no_succ),
            'long_duration': int((duration > 60).sum()),
            'positive_lag': int((lag > 0).sum()),
            'negative_lag': int((lag < 0).sum()),
            'not_started': int((statuses == 'not started').sum()),
            'in_progress': int(statuses.str.contains('progress').sum()),
            'completed': int(statuses.str.contains('complete').sum()),
            'project_start': task['start_date'].min().strftime('%Y-%m-%d') if task['start_date'].notna().any() else None,
            'project_finish': task['end_date'].max().strftime('%Y-%m-%d') if task['end_date'].notna().any() else None,
            'schedule_health': score,
        },
        'issues': issues,
        'open_start_ids': no_pred,
        'open_finish_ids': no_succ,
        'activities': activities.to_dict(orient='records'),
    }
