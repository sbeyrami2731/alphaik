from __future__ import annotations

import io
import logging

from typing import Any

import pandas as pd


logger = logging.getLogger("uvicorn.error")


TASK_COLUMNS = {
    "task_code": "activity_id",
    "wbs_id": "wbs",
    "task_name": "activity_name",
    "target_drtn_hr_cnt": "original_duration",
    "start_date": "start",
    "end_date": "finish",
    "remain_drtn_hr_cnt": "remaining_duration",
    "pred_list": "predecessors",
    "succ_list": "successors",
    "total_float_hr_cnt": "total_float",
    "status_code": "status",
}


def _clean_sheet(
    df: pd.DataFrame,
    id_col: str
) -> pd.DataFrame:

    if df.empty:
        return df

    first_value = str(
        df.iloc[0].get(
            id_col,
            ""
        )
    ).strip().lower()

    if first_value in {
        "activity id",
        "predecessor"
    }:
        df = df.iloc[1:].copy()

    return df.reset_index(
        drop=True
    )


def _normalize_datetime_column(
    series: pd.Series
) -> pd.Series:

    if pd.api.types.is_datetime64_any_dtype(
        series
    ):
        return series

    return pd.to_datetime(
        series,
        errors="coerce",
        format="mixed"
    )


def parse_workbook(
    content: bytes
) -> tuple[pd.DataFrame, pd.DataFrame]:

    book = pd.ExcelFile(
        io.BytesIO(content)
    )

    if (
        "TASK" not in book.sheet_names
        or "TASKPRED" not in book.sheet_names
    ):
        raise ValueError(
            "Workbook must contain TASK and TASKPRED sheets."
        )

    task = _clean_sheet(
        pd.read_excel(
            book,
            "TASK"
        ),
        "task_code"
    )

    relationships = _clean_sheet(
        pd.read_excel(
            book,
            "TASKPRED"
        ),
        "pred_task_id"
    )

    return task, relationships


def analyze(
    task: pd.DataFrame,
    rel: pd.DataFrame
) -> dict[str, Any]:

    logger.info(
        "ALPHAIK_ANALYZE_STEP: 01_START"
    )

    # ========================================================
    # Required columns
    # ========================================================

    required_task_columns = {
        "task_code",
        "target_drtn_hr_cnt",
        "remain_drtn_hr_cnt",
        "total_float_hr_cnt",
        "status_code",
        "start_date",
        "end_date",
    }

    required_relationship_columns = {
        "pred_task_id",
        "task_id",
        "lag_hr_cnt",
    }

    missing_task = (
        required_task_columns
        - set(task.columns)
    )

    missing_relationships = (
        required_relationship_columns
        - set(rel.columns)
    )

    if missing_task:
        raise ValueError(
            "TASK sheet is missing required columns: "
            + ", ".join(
                sorted(missing_task)
            )
        )

    if missing_relationships:
        raise ValueError(
            "TASKPRED sheet is missing required columns: "
            + ", ".join(
                sorted(missing_relationships)
            )
        )

    logger.info(
        "ALPHAIK_ANALYZE_STEP: 02_COLUMNS_OK"
    )

    # ========================================================
    # Numeric normalization
    # ========================================================

    for col in [
        "target_drtn_hr_cnt",
        "remain_drtn_hr_cnt",
        "total_float_hr_cnt",
    ]:
        task[col] = pd.to_numeric(
            task[col],
            errors="coerce"
        )

    rel["lag_hr_cnt"] = pd.to_numeric(
        rel["lag_hr_cnt"],
        errors="coerce"
    )

    logger.info(
        "ALPHAIK_ANALYZE_STEP: 03_NUMERIC_OK"
    )

    # ========================================================
    # Date normalization
    # ========================================================

    logger.info(
        "ALPHAIK_ANALYZE_STEP: 03A_START_DATE_BEGIN"
    )

    task["start_date"] = (
        _normalize_datetime_column(
            task["start_date"]
        )
    )

    logger.info(
        "ALPHAIK_ANALYZE_STEP: 03B_START_DATE_OK"
    )

    logger.info(
        "ALPHAIK_ANALYZE_STEP: 03C_END_DATE_BEGIN"
    )

    task["end_date"] = (
        _normalize_datetime_column(
            task["end_date"]
        )
    )

    logger.info(
        "ALPHAIK_ANALYZE_STEP: 03D_END_DATE_OK"
    )

    logger.info(
        "ALPHAIK_ANALYZE_STEP: 04_DATES_OK"
    )

    # ========================================================
    # Relationship analysis
    # ========================================================

    activity_ids = set(
        task["task_code"]
        .dropna()
        .astype(str)
    )

    predecessor_ids = set(
        rel["pred_task_id"]
        .dropna()
        .astype(str)
    )

    successor_ids = set(
        rel["task_id"]
        .dropna()
        .astype(str)
    )

    no_pred = sorted(
        activity_ids
        - successor_ids
    )

    no_succ = sorted(
        activity_ids
        - predecessor_ids
    )

    logger.info(
        "ALPHAIK_ANALYZE_STEP: 05_RELATIONSHIPS_OK"
    )

    # ========================================================
    # Core metrics
    # ========================================================

    total_float = (
        task["total_float_hr_cnt"]
    )

    duration = (
        task["target_drtn_hr_cnt"]
    )

    lag = (
        rel["lag_hr_cnt"]
    )

    statuses = (
        task["status_code"]
        .fillna("")
        .astype(str)
        .str.lower()
    )

    logger.info(
        "ALPHAIK_ANALYZE_STEP: 06_METRICS_OK"
    )

    # ========================================================
    # Findings
    # ========================================================

    issues = []

    if no_pred:
        issues.append(
            {
                "severity": "warning",
                "type": "OPEN_START",
                "count": len(no_pred),
                "message": "Activities without predecessor",
            }
        )

    if no_succ:
        issues.append(
            {
                "severity": "warning",
                "type": "OPEN_FINISH",
                "count": len(no_succ),
                "message": "Activities without successor",
            }
        )

    if (lag < 0).any():
        issues.append(
            {
                "severity": "critical",
                "type": "LEAD",
                "count": int(
                    (lag < 0).sum()
                ),
                "message": "Negative lags detected",
            }
        )

    if (lag > 10).any():
        issues.append(
            {
                "severity": "warning",
                "type": "LONG_LAG",
                "count": int(
                    (lag > 10).sum()
                ),
                "message": (
                    "Relationships with lag > 10 days"
                ),
            }
        )

    if (duration > 60).any():
        issues.append(
            {
                "severity": "warning",
                "type": "LONG_DURATION",
                "count": int(
                    (duration > 60).sum()
                ),
                "message": (
                    "Activities longer than 60 days"
                ),
            }
        )

    if (total_float < 0).any():
        issues.append(
            {
                "severity": "critical",
                "type": "NEGATIVE_FLOAT",
                "count": int(
                    (total_float < 0).sum()
                ),
                "message": (
                    "Negative float activities"
                ),
            }
        )

    logger.info(
        "ALPHAIK_ANALYZE_STEP: 07_FINDINGS_OK"
    )

    # ========================================================
    # Health score
    # ========================================================

    score = 100

    score -= min(
        15,
        len(no_pred) * 0.5
    )

    score -= min(
        15,
        len(no_succ) * 0.35
    )

    score -= min(
        15,
        int(
            (lag < 0).sum()
        ) * 5
    )

    score -= min(
        10,
        int(
            (lag > 10).sum()
        )
    )

    score -= min(
        15,
        int(
            (duration > 60).sum()
        ) * 0.15
    )

    score -= min(
        20,
        int(
            (total_float < 0).sum()
        ) * 4
    )

    score = max(
        0,
        round(
            score,
            1
        )
    )

    logger.info(
        "ALPHAIK_ANALYZE_STEP: 08_SCORE_OK"
    )

    # ========================================================
    # Activity output
    # ========================================================

    columns = [
        column
        for column in TASK_COLUMNS
        if column in task.columns
    ]

    activities = (
        task[columns]
        .rename(
            columns=TASK_COLUMNS
        )
        .copy()
    )

    logger.info(
        "ALPHAIK_ANALYZE_STEP: 09_ACTIVITY_FRAME_OK"
    )

    for col in [
        "start",
        "finish",
    ]:
        if col in activities.columns:

            activities[col] = (
                activities[col]
                .dt.strftime(
                    "%Y-%m-%d"
                )
            )

    activities = (
        activities
        .astype(object)
        .where(
            pd.notna(activities),
            None
        )
    )

    logger.info(
        "ALPHAIK_ANALYZE_STEP: 10_ACTIVITY_CLEANUP_OK"
    )

    # ========================================================
    # Project dates
    # ========================================================

    project_start = None
    project_finish = None

    if task["start_date"].notna().any():

        project_start = (
            task["start_date"]
            .min()
            .strftime(
                "%Y-%m-%d"
            )
        )

    if task["end_date"].notna().any():

        project_finish = (
            task["end_date"]
            .max()
            .strftime(
                "%Y-%m-%d"
            )
        )

    logger.info(
        "ALPHAIK_ANALYZE_STEP: 11_DATES_SUMMARY_OK"
    )

    # ========================================================
    # Final result
    # ========================================================

    result = {
        "summary": {
            "activities": int(
                len(task)
            ),
            "relationships": int(
                len(rel)
            ),
            "critical": int(
                (total_float <= 0).sum()
            ),
            "near_critical": int(
                (
                    (total_float > 0)
                    & (total_float <= 10)
                ).sum()
            ),
            "negative_float": int(
                (total_float < 0).sum()
            ),
            "open_start": len(
                no_pred
            ),
            "open_finish": len(
                no_succ
            ),
            "long_duration": int(
                (duration > 60).sum()
            ),
            "positive_lag": int(
                (lag > 0).sum()
            ),
            "negative_lag": int(
                (lag < 0).sum()
            ),
            "not_started": int(
                (
                    statuses
                    == "not started"
                ).sum()
            ),
            "in_progress": int(
                statuses
                .str.contains(
                    "progress"
                )
                .sum()
            ),
            "completed": int(
                statuses
                .str.contains(
                    "complete"
                )
                .sum()
            ),
            "project_start": (
                project_start
            ),
            "project_finish": (
                project_finish
            ),
            "schedule_health": (
                score
            ),
        },
        "issues": issues,
        "open_start_ids": no_pred,
        "open_finish_ids": no_succ,
        "activities": (
            activities.to_dict(
                orient="records"
            )
        ),
    }

    logger.info(
        "ALPHAIK_ANALYZE_STEP: 12_COMPLETED"
    )

    return result
