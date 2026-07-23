#!/usr/bin/env python3
import argparse
import fcntl
import json
import os
from datetime import datetime
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import server  # noqa: E402


SNAPSHOT_PATH = server.DATA_DIR / "mobile_snapshot.json"
STATE_PATH = server.DATA_DIR / "scheduled_refresh_state.json"
LOCK_PATH = server.DATA_DIR / "scheduled_refresh.lock"


def mode_options(mode):
    return {
        "refresh_kline": mode in {"midday", "close"},
        "refresh_sentiment": mode in {"midday", "close"},
    }


def atomic_write_json(path, payload):
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)
        file.flush()
        os.fsync(file.fileno())
    temporary.replace(path)


def is_scheduled_trading_day(now):
    return now.weekday() < 5 and now.date().isoformat() not in server.MARKET_HOLIDAYS


def bridge_is_fresh(max_age_minutes):
    status = server.tdx_bridge_status()
    generated_at = server.parse_timestamp(status.get("generatedAt"))
    if not status.get("available") or not generated_at:
        return False, "WorkBuddy桥接数据不存在或缺少生成时间。"
    age_seconds = max(0, datetime.now().timestamp() - generated_at)
    if age_seconds > max_age_minutes * 60:
        return False, f"WorkBuddy桥接已超过{max_age_minutes}分钟，本轮不覆盖旧快照。"
    return True, "WorkBuddy桥接已按时更新。"


def latest_evaluation_quote_time(evaluations):
    values = []
    for evaluation in evaluations.values():
        quote = (evaluation.get("stock") or {}).get("quote") or {}
        quote_date = str(quote.get("quoteTime") or "").strip()
        quote_clock = str(quote.get("quoteClock") or "").strip()
        if quote_date:
            values.append(f"{quote_date} {quote_clock}".strip())
    return max(values) if values else None


def evaluation_quote_providers(evaluations):
    return sorted(
        {
            str(((evaluation.get("stock") or {}).get("quote") or {}).get("source"))
            for evaluation in evaluations.values()
            if ((evaluation.get("stock") or {}).get("quote") or {}).get("source")
        }
    )


def run(
    mode,
    force=False,
    require_fresh_bridge_minutes=None,
    minimum_evaluation_ratio=0,
):
    now = datetime.now()
    if not force and not is_scheduled_trading_day(now):
        return {"ok": True, "skipped": True, "reason": "非交易日，保留上一版快照。"}
    if require_fresh_bridge_minutes:
        fresh, reason = bridge_is_fresh(require_fresh_bridge_minutes)
        if not fresh:
            state = {
                "ok": False,
                "skipped": True,
                "mode": mode,
                "checkedAt": server.now_text(),
                "reason": reason,
                "previousSnapshotKept": SNAPSHOT_PATH.exists(),
            }
            atomic_write_json(STATE_PATH, state)
            return state

    options = mode_options(mode)
    started_at = server.now_text()
    try:
        payload = server.refresh_home_data(**options)
        evaluations = {}
        for item in server.read_watchlist().get("items", []):
            code = item.get("code")
            if code:
                evaluations[code] = server.evaluate_stock(code, use_intraday=True)
        evaluated_count = sum(
            1
            for evaluation in evaluations.values()
            if (evaluation.get("stock") or {}).get("hasScore")
        )
        evaluation_ratio = evaluated_count / max(1, len(evaluations))
        if evaluation_ratio < minimum_evaluation_ratio:
            raise RuntimeError(
                "完整评分仅"
                f"{evaluated_count}/{len(evaluations)}，低于发布门槛"
                f"{minimum_evaluation_ratio:.0%}，保留上一版手机快照。"
            )
        sector_details = {
            group: server.build_sector_detail(group)
            for group, _keywords in server.THEME_GROUP_RULES
        }
        completed_at = server.now_text()
        bridge_status = server.tdx_bridge_status()
        level_basis = {
            "hourly": "盘中动态，收盘待确认",
            "midday": "午间暂定，收盘待确认",
            "close": "收盘确认",
        }[mode]
        snapshot = {
            **payload,
            "ok": True,
            "mode": mode,
            "scheduledAt": started_at,
            "completedAt": completed_at,
            "refreshKline": options["refresh_kline"],
            "refreshSentiment": options["refresh_sentiment"],
            "dataStatus": {
                "quoteAsOf": (
                    latest_evaluation_quote_time(evaluations)
                    or bridge_status.get("generatedAt")
                    or payload.get("updatedAt")
                ),
                "analysisAsOf": completed_at,
                "levelBasis": level_basis,
                "adviceBasis": "最新报价 + 日周月结构 + 板块强度",
                "source": server.DATA_SOURCE_LABEL,
                "quoteProviders": evaluation_quote_providers(evaluations),
                "evaluatedCount": evaluated_count,
                "evaluationCount": len(evaluations),
            },
            "provider": {"provider": server.provider_status(), "ths": server.provider_status()},
            "evaluations": evaluations,
            "sectorDetails": sector_details,
        }
        atomic_write_json(SNAPSHOT_PATH, snapshot)
        atomic_write_json(STATE_PATH, {
            "ok": True,
            "mode": mode,
            "startedAt": started_at,
            "completedAt": snapshot["completedAt"],
            "snapshotPath": str(SNAPSHOT_PATH),
        })
        return snapshot
    except Exception as error:
        failure = {
            "ok": False,
            "mode": mode,
            "startedAt": started_at,
            "failedAt": server.now_text(),
            "reason": str(error),
            "previousSnapshotKept": SNAPSHOT_PATH.exists(),
        }
        atomic_write_json(STATE_PATH, failure)
        raise


def main():
    parser = argparse.ArgumentParser(description="刷新手机端云快照")
    parser.add_argument("--mode", choices=("hourly", "midday", "close"), required=True)
    parser.add_argument("--force", action="store_true", help="测试时忽略周末和休市日")
    parser.add_argument(
        "--require-fresh-bridge-minutes",
        type=int,
        default=None,
        help="仅在WorkBuddy桥接于指定分钟内更新时生成快照",
    )
    parser.add_argument(
        "--minimum-evaluation-ratio",
        type=float,
        default=0,
        help="完整评分比例低于该值时拒绝发布，范围0-1",
    )
    args = parser.parse_args()

    LOCK_PATH.touch(exist_ok=True)
    with LOCK_PATH.open("r+") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("已有刷新任务运行，本次跳过。")
            return
        result = run(
            args.mode,
            force=args.force,
            require_fresh_bridge_minutes=args.require_fresh_bridge_minutes,
            minimum_evaluation_ratio=args.minimum_evaluation_ratio,
        )

    if result.get("skipped"):
        print(result["reason"])
        return
    print(
        f"手机快照更新完成：{result['mode']}，"
        f"K线={'是' if result['refreshKline'] else '否'}，"
        f"市场情绪={'是' if result['refreshSentiment'] else '否'}，"
        f"完成时间={result['completedAt']}"
    )


if __name__ == "__main__":
    main()
