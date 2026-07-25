from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from datetime import datetime, timedelta
import http.client
import html
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request


ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("APP_DATA_DIR", ROOT / "data"))
CACHE_DIR = DATA_DIR / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

CACHE_TTL_SECONDS = 30 * 60
QUOTE_CACHE_TTL_SECONDS = int(os.environ.get("QUOTE_CACHE_TTL_SECONDS", "8"))
KLINE_CACHE_TTL_SECONDS = 6 * 60 * 60
FUNDAMENTAL_CACHE_TTL_SECONDS = 7 * 24 * 60 * 60
THEME_CACHE_TTL_SECONDS = 24 * 60 * 60
MARKET_SENTIMENT_CACHE_TTL_SECONDS = 30 * 60
CACHE_SCHEMA_VERSION = 3
MIN_EXTERNAL_INTERVAL_SECONDS = float(os.environ.get("MIN_EXTERNAL_INTERVAL_SECONDS", "5"))
PROVIDER_COOLDOWN_SECONDS = int(os.environ.get("PROVIDER_COOLDOWN_SECONDS", str(5 * 60)))
PROVIDER_REQUEST_RETRIES = int(os.environ.get("PROVIDER_REQUEST_RETRIES", "1"))
PROVIDER_RETRY_DELAY_SECONDS = float(os.environ.get("PROVIDER_RETRY_DELAY_SECONDS", "1.5"))
MARKET_HOLIDAYS = {
    "2026-06-19",
}
ENABLE_THS = os.environ.get("ENABLE_THS", "1") == "1"
ENABLE_EASTMONEY = os.environ.get("ENABLE_EASTMONEY", "0") == "1"
ENABLE_TENCENT = os.environ.get("ENABLE_TENCENT", "0") == "1"
DATA_SOURCE_LABEL = os.environ.get("DATA_SOURCE_LABEL", "WorkBuddy通达信桥接")
PROVIDER_STATE_PATH = CACHE_DIR / "ths_provider_state.json"
MARKET_SENTIMENT_CACHE_PATH = CACHE_DIR / "market_sentiment.json"
FULL_MARKET_REFRESH_STATE_PATH = DATA_DIR / "full_market_refresh_state.json"
WATCHLIST_PATH = DATA_DIR / "watchlist.json"
TDX_BRIDGE_DIR = Path(os.environ.get("TDX_BRIDGE_DIR", DATA_DIR / "tdx_bridge"))
TDX_BRIDGE_MANIFEST_PATH = TDX_BRIDGE_DIR / "manifest.json"
TDX_BRIDGE_QUOTES_PATH = TDX_BRIDGE_DIR / "watchlist_quotes.json"
TDX_BRIDGE_KLINES_DIR = TDX_BRIDGE_DIR / "klines"
TDX_BRIDGE_QUOTE_MAX_AGE_SECONDS = 36 * 60 * 60
ALLOW_LAGGING_KLINE_SEED = os.environ.get("ALLOW_LAGGING_KLINE_SEED", "0") == "1"
KLINE_SEED_MAX_GAP_DAYS = int(os.environ.get("KLINE_SEED_MAX_GAP_DAYS", "4"))
MAINLINE_SAMPLE_PATH = DATA_DIR / "mainline_sample_100.json"
CLASSIFIED_SAMPLE_PATHS = [
    DATA_DIR / "backtest_sample_all_classified.json",
    DATA_DIR / "backtest_sample_1500_classified.json",
    DATA_DIR / "backtest_sample_500_classified.json",
]
PROVIDER_LOCK = threading.Lock()
MARKET_SENTIMENT_LOCK = threading.Lock()
MARKET_SENTIMENT_REFRESHING = False


def load_json(path):
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def full_market_refresh_progress():
    if not FULL_MARKET_REFRESH_STATE_PATH.exists():
        return {"available": False, "status": "not_started"}
    try:
        state = load_json(FULL_MARKET_REFRESH_STATE_PATH)
    except (OSError, json.JSONDecodeError):
        return {"available": False, "status": "unavailable"}

    target = int(state.get("target") or 0)
    completed = {
        "kline": int(state.get("klineCompleted") or 0),
        "theme": int(state.get("themeCompleted") or 0),
        "fundamental": int(state.get("fundamentalCompleted") or 0),
    }
    missing = {
        "kline": int(state.get("klineMissing") or 0),
        "theme": int(state.get("themeMissing") or 0),
        "fundamental": int(state.get("fundamentalMissing") or 0),
    }
    total_units = target * 3
    done_units = sum(completed.values())
    resolved_units = done_units + sum(missing.values())
    current = state.get("current") or {}
    started_at = state.get("startedAt")
    elapsed = max(1, int(time.time() - started_at)) if started_at else None
    processed_this_run = int(current.get("index") or 0)
    rate_per_hour = (
        round(processed_this_run / elapsed * 3600, 1)
        if elapsed and processed_this_run
        else None
    )
    remaining_requests = max(0, total_units - done_units)
    interval = state.get("requestIntervalSeconds") or {}
    min_interval = float(interval.get("min") or MIN_EXTERNAL_INTERVAL_SECONDS)
    max_interval = float(interval.get("max") or MIN_EXTERNAL_INTERVAL_SECONDS)
    average_interval = (min_interval + max_interval) / 2
    raw_stage = str(state.get("stage") or "")
    current_stage = raw_stage.replace("_cooling", "")
    if current_stage not in completed:
        current_stage = next(
            (stage for stage in ("kline", "theme", "fundamental") if completed[stage] < target),
            None,
        )
    current_stage_completed = completed.get(current_stage, 0) if current_stage else done_units
    current_stage_remaining = (
        max(0, target - current_stage_completed)
        if current_stage and target
        else remaining_requests
    )
    current_stage_estimated_seconds = (
        round(current_stage_remaining * average_interval)
        if state.get("status") == "running"
        else None
    )
    full_estimated_seconds = (
        round(remaining_requests * average_interval)
        if state.get("status") == "running"
        else None
    )
    estimated_seconds = None
    if rate_per_hour:
        estimated_seconds = round(remaining_requests / rate_per_hour * 3600)
    elif state.get("status") == "running":
        estimated_seconds = full_estimated_seconds

    return {
        **state,
        "available": True,
        "completed": completed,
        "missing": missing,
        "overallCompleted": done_units,
        "overallTotal": total_units,
        "overallPct": round(resolved_units / total_units * 100, 1) if total_units else 0,
        "usableComplete": state.get("status") == "complete" or (total_units > 0 and resolved_units >= total_units),
        "completionNote": (
            f"补全已结束；日K缺口{missing['kline']}只、题材缺口{missing['theme']}只、基本面缺口{missing['fundamental']}只，多为新股或源站暂无数据。"
            if state.get("status") == "complete"
            else None
        ),
        "processedThisRun": processed_this_run,
        "ratePerHour": rate_per_hour,
        "currentStage": current_stage,
        "currentStageCompleted": current_stage_completed,
        "currentStageRemaining": current_stage_remaining,
        "currentStageEstimatedSeconds": current_stage_estimated_seconds,
        "remainingRequests": remaining_requests,
        "estimatedSeconds": estimated_seconds,
        "fullEstimatedSeconds": full_estimated_seconds,
        "serverTime": int(time.time()),
    }


STOCK_MASTER = load_json(DATA_DIR / "stock_master.json")
ETF_MASTER = {
    "159516": {
        "code": "159516",
        "name": "半导体设备材料ETF",
        "market": "深市ETF",
        "industry": "ETF/半导体设备材料",
        "displayIndustry": "ETF/半导体设备材料",
        "isST": False,
        "isETF": True,
    },
    "561980": {
        "code": "561980",
        "name": "半导体设备ETF",
        "market": "沪市ETF",
        "industry": "ETF/半导体设备",
        "displayIndustry": "ETF/半导体设备",
        "isST": False,
        "isETF": True,
    },
}
DEMO_SCORES = load_json(DATA_DIR / "demo_scores.json")


def default_provider_state():
    return {
        "lastExternalAt": 0,
        "blockedUntil": 0,
        "failCount": 0,
        "lastError": "",
    }


def read_provider_state():
    if not PROVIDER_STATE_PATH.exists():
        return default_provider_state()
    try:
        return {**default_provider_state(), **load_json(PROVIDER_STATE_PATH)}
    except json.JSONDecodeError:
        return default_provider_state()


def write_provider_state(state):
    with PROVIDER_STATE_PATH.open("w", encoding="utf-8") as file:
        json.dump(state, file, ensure_ascii=False, indent=2)


def now_text():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def parse_timestamp(value):
    if isinstance(value, (int, float)):
        return float(value)
    raw_text = str(value or "").strip()
    try:
        return datetime.fromisoformat(raw_text.replace("Z", "+00:00")).timestamp()
    except ValueError:
        pass
    text = raw_text.replace("T", " ").replace("Z", "")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).timestamp()
        except ValueError:
            continue
    return None


def safe_load_json(path):
    try:
        return load_json(path)
    except (OSError, json.JSONDecodeError, TypeError):
        return None


def bridge_float(value):
    if value in (None, "", "-", "--"):
        return None
    try:
        return float(str(value).replace(",", "").replace("%", "").strip())
    except (TypeError, ValueError):
        return None


def normalize_security_code(value):
    match = re.search(r"(\d{6})", str(value or ""))
    return match.group(1) if match else ""


def bridge_generated_at(payload, path):
    if isinstance(payload, dict):
        value = payload.get("generatedAt") or payload.get("fetchedAt") or payload.get("updatedAt")
        parsed = parse_timestamp(value)
        if parsed:
            return parsed
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def tdx_bridge_status():
    manifest = safe_load_json(TDX_BRIDGE_MANIFEST_PATH) or {}
    quote_payload = safe_load_json(TDX_BRIDGE_QUOTES_PATH)
    quote_generated_at = bridge_generated_at(quote_payload, TDX_BRIDGE_QUOTES_PATH) if quote_payload else None
    kline_count = 0
    try:
        kline_count = sum(1 for path in TDX_BRIDGE_KLINES_DIR.glob("*_daily.json") if path.is_file())
    except OSError:
        pass
    return {
        "enabled": True,
        "available": bool(manifest or quote_payload or kline_count),
        "directory": str(TDX_BRIDGE_DIR),
        "schemaVersion": manifest.get("schemaVersion"),
        "generatedAt": manifest.get("generatedAt"),
        "asOfDate": manifest.get("asOfDate"),
        "quoteCount": len(bridge_quote_rows(quote_payload)) if quote_payload else 0,
        "quoteAgeSeconds": max(0, int(time.time() - quote_generated_at)) if quote_generated_at else None,
        "dailyKlineFileCount": kline_count,
        "source": manifest.get("source") or "workbuddy-tdx",
        "note": manifest.get("note"),
    }


def read_watchlist():
    if not WATCHLIST_PATH.exists():
        return {"items": []}
    try:
        payload = load_json(WATCHLIST_PATH)
    except (OSError, json.JSONDecodeError):
        return {"items": []}
    items = payload.get("items") if isinstance(payload, dict) else []
    return {"items": items if isinstance(items, list) else []}


def write_watchlist(payload):
    WATCHLIST_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def build_watchlist_advice(stock, item):
    plan = stock.get("executionPlan") or {}
    strength = stock.get("strength") or {}
    group_state = strength.get("groupState") or {}
    sector = strength.get("sectorThesis") or {}
    priority = strength.get("priority") or {}
    timeframes = stock.get("timeframes") or {}
    gate = plan.get("executionGate") or stock.get("setupType") or "观察"
    trial_status = plan.get("trialStatus")
    priority_level = priority.get("level") or ""
    group = strength.get("group") or item.get("industry") or "待分类"
    block_reasons = plan.get("blockReasons") or []
    stale_only = block_reasons and all(
        reason.startswith(("行情仅到", "最新价已到")) for reason in block_reasons
    )

    if group_state.get("gate") == "禁止加权" or sector.get("phase") == "退潮":
        return {
            "adviceRank": 80,
            "aiAction": "降权观察",
            "aiNote": f"{group}退潮或降温，只看修复，不主动加仓。",
            "aiTags": ["退潮", "只看修复"],
            "aiUpdatedAt": now_text(),
        }

    if trial_status in ("次日确认", "日内回收", "抛压衰竭待回收") and gate in ("允许轻仓试错", "谨慎试错", "允许极小仓低吸"):
        return {
            "adviceRank": 10,
            "aiAction": "可试错",
            "aiNote": "低位已出现释放或回收，按阶段控制小仓，跌破失效位先处理。",
            "aiTags": ["流动性低点", "小仓"],
            "aiUpdatedAt": now_text(),
        }

    if trial_status in ("低吸区内待触发", "抛压衰竭待回收", "日内回收", "次日确认") and stale_only:
        return {
            "adviceRank": 15,
            "aiAction": "刷新确认",
            "aiNote": "位置接近可操作区，但行情缓存偏旧，刷新后再决定是否试错。",
            "aiTags": ["待刷新", "接近买点"],
            "aiUpdatedAt": now_text(),
        }

    if priority_level in ("A", "A-") and trial_status in ("高于低吸区", "确认已过等待回踩"):
        return {
            "adviceRank": 20,
            "aiAction": "等回踩",
            "aiNote": f"{group}强主线强股，但当前高于计划低吸区，新仓不追。",
            "aiTags": ["强主线", "等回落", "不追高"],
            "aiUpdatedAt": now_text(),
        }

    if priority_level in ("A", "A-"):
        return {
            "adviceRank": 30,
            "aiAction": "重点观察",
            "aiNote": f"{group}方向和个股强度较好，等待日线动作转为可试错。",
            "aiTags": ["强方向", "观察"],
            "aiUpdatedAt": now_text(),
        }

    if timeframes.get("posture") == "降低仓位":
        return {
            "adviceRank": 75,
            "aiAction": "轻仓修复",
            "aiNote": "上级周期不支持重仓，日线反弹先按修复处理。",
            "aiTags": ["轻仓", "修复"],
            "aiUpdatedAt": now_text(),
        }

    return {
        "adviceRank": 60,
        "aiAction": "普通观察",
        "aiNote": "强度或买点未形成共振，先等价格重新确认。",
        "aiTags": ["观察"],
        "aiUpdatedAt": now_text(),
    }


def stock_total_score(stock):
    scores = stock.get("scores") or {}
    values = [value for value in scores.values() if isinstance(value, (int, float))]
    return sum(values) if values else stock.get("totalScore")


def watchlist_item_from_stock(stock):
    quote = stock.get("quote") or {}
    plan = stock.get("executionPlan") or {}
    strength = stock.get("strength") or {}
    decision_loop = stock.get("decisionLoop") or {}
    item = {
        "code": stock.get("code"),
        "name": stock.get("name"),
        "industry": stock.get("displayIndustry") or stock.get("industry") or strength.get("group") or "待分类",
        "lastScore": stock_total_score(stock),
        "lastAction": plan.get("executionGate") or stock.get("setupType") or "观察",
        "mainline": decision_loop.get("mainline"),
        "cycle": decision_loop.get("cycle"),
        "passivePlan": decision_loop.get("passive"),
        "riskLine": decision_loop.get("risk"),
        "fundamentalLine": decision_loop.get("fundamental"),
        "trialStatus": plan.get("trialStatus"),
        "lastPrice": quote.get("price") if isinstance(quote, dict) else stock.get("price"),
        "trialRange": (
            f"{plan.get('trialLow'):.2f}-{plan.get('trialHigh'):.2f}"
            if isinstance(plan.get("trialLow"), (int, float)) and isinstance(plan.get("trialHigh"), (int, float))
            else None
        ),
        "invalid": plan.get("invalidPrice") or stock.get("invalid"),
        "lastUpdatedAt": now_text(),
    }
    item.update(build_watchlist_advice(stock, item))
    return item


def watchlist_battle_groups(items):
    buckets = [
        ("可试错", "可以小仓按计划试错", lambda item: item.get("aiAction") in ("可试错", "刷新确认")),
        ("等回踩", "强方向不追高，等进入计划区", lambda item: item.get("aiAction") in ("等回踩", "重点观察")),
        ("修复观察", "只看修复和承接，不主动加仓", lambda item: item.get("aiAction") in ("轻仓修复", "普通观察")),
        ("降权处理", "退潮或弱势，反弹优先降被动", lambda item: item.get("aiAction") in ("降权观察",)),
    ]
    used_codes = set()
    groups = []
    for key, label, matcher in buckets:
        matched = [item for item in items if item.get("code") not in used_codes and matcher(item)]
        used_codes.update(item.get("code") for item in matched)
        groups.append(
            {
                "key": key,
                "label": label,
                "count": len(matched),
                "items": [
                    {
                        "code": item.get("code"),
                        "name": item.get("name"),
                        "action": item.get("aiAction"),
                        "note": item.get("aiNote"),
                    }
                    for item in matched[:4]
                ],
            }
        )
    return groups


def watchlist_response():
    payload = read_watchlist()
    items = sorted(payload["items"], key=lambda item: (item.get("adviceRank", 99), item.get("addedAt", "")))
    for item in items:
        item.setdefault("mainline", item.get("industry"))
        item.setdefault("passivePlan", item.get("aiNote") or item.get("note"))
        item.setdefault("riskLine", f"失效位 {item['invalid']:.2f}" if isinstance(item.get("invalid"), (int, float)) else None)
    return {"ok": True, "items": items, "count": len(items), "battleGroups": watchlist_battle_groups(items)}


def build_daily_brief():
    watchlist = watchlist_response()
    sectors = build_sector_rankings(limit=12)
    sentiment = market_sentiment_status(refresh=False)
    market_state = (sentiment.get("marketState") or {}) if sentiment.get("ok") else {}
    position_switch = market_state.get("positionSwitch") or {}

    sector_groups = sectors.get("actionGroups") or []
    sector_by_action = {item.get("key"): item for item in sector_groups}
    watch_groups = watchlist.get("battleGroups") or []
    watch_by_action = {item.get("key"): item for item in watch_groups}

    focus_groups = []
    for action in ("回调优先", "等待突破", "只做核心"):
        group = sector_by_action.get(action) or {}
        if group.get("count"):
            focus_groups.extend(group.get("groups") or [])
    focus_groups = list(dict.fromkeys(focus_groups))[:8]

    action_items = []
    for key in ("可试错", "等回踩", "修复观察", "降权处理"):
        group = watch_by_action.get(key) or {}
        for item in group.get("items") or []:
            action_items.append(
                {
                    "bucket": key,
                    "code": item.get("code"),
                    "name": item.get("name"),
                    "action": item.get("action"),
                    "note": item.get("note"),
                }
            )

    if (watch_by_action.get("可试错") or {}).get("count"):
        primary_action = "先处理可试错票，仓位仍按失效位小仓验证。"
    elif (watch_by_action.get("等回踩") or {}).get("count"):
        primary_action = "当前主要任务是等强方向核心股回踩，不追高。"
    elif (watch_by_action.get("降权处理") or {}).get("count"):
        primary_action = "优先处理降权票，反弹以降低被动为主。"
    else:
        primary_action = "没有明确进攻票，先观察板块轮动和个股承接。"

    notes = [
        f"市场状态：{market_state.get('state') or '待确认'}；仓位开关：{position_switch.get('level') or '待确认'}。",
        f"板块回调优先 {sector_by_action.get('回调优先', {}).get('count', 0)} 个，只做核心 {sector_by_action.get('只做核心', {}).get('count', 0)} 个，回避加仓 {sector_by_action.get('回避加仓', {}).get('count', 0)} 个。",
        f"选股池：可试错 {(watch_by_action.get('可试错') or {}).get('count', 0)}，等回踩 {(watch_by_action.get('等回踩') or {}).get('count', 0)}，降权处理 {(watch_by_action.get('降权处理') or {}).get('count', 0)}。",
        primary_action,
    ]

    return {
        "ok": True,
        "updatedAt": now_text(),
        "market": {
            "state": market_state.get("state") or "待确认",
            "upRatio": market_state.get("upRatio"),
            "position": position_switch.get("level") or "待确认",
            "action": position_switch.get("action") or "等待确认",
            "stale": sentiment.get("stale") if isinstance(sentiment, dict) else None,
        },
        "sectorActions": sector_groups,
        "watchlistActions": watch_groups,
        "focusGroups": focus_groups,
        "actionItems": action_items[:12],
        "notes": notes,
    }


def add_watchlist_item(stock_payload):
    stock = stock_payload.get("stock") if isinstance(stock_payload, dict) else None
    if not isinstance(stock, dict) or not stock.get("code") or stock.get("code") in ("未识别", "------"):
        return {"ok": False, "reason": "没有有效股票代码，无法加入选股池。"}
    item = watchlist_item_from_stock(stock)
    requested_tags = stock_payload.get("tags") if isinstance(stock_payload, dict) else None
    requested_note = stock_payload.get("note") if isinstance(stock_payload, dict) else None
    if isinstance(requested_tags, list):
        item["tags"] = list(dict.fromkeys(str(tag).strip() for tag in requested_tags if str(tag).strip()))
    if isinstance(requested_note, str):
        item["note"] = requested_note.strip()
    payload = read_watchlist()
    existing = next((entry for entry in payload["items"] if entry.get("code") == item["code"]), None)
    if existing:
        existing.update({key: value for key, value in item.items() if value is not None})
        existing.setdefault("addedAt", now_text())
    else:
        item["addedAt"] = now_text()
        item.setdefault("note", "")
        item.setdefault("tags", [])
        payload["items"].insert(0, item)
    write_watchlist(payload)
    return {
        "ok": True,
        "item": existing or item,
        "items": payload["items"],
        "count": len(payload["items"]),
        "battleGroups": watchlist_battle_groups(payload["items"]),
    }


def remove_watchlist_item(code):
    payload = read_watchlist()
    before = len(payload["items"])
    payload["items"] = [item for item in payload["items"] if item.get("code") != code]
    write_watchlist(payload)
    return {
        "ok": True,
        "removed": before - len(payload["items"]),
        "items": payload["items"],
        "count": len(payload["items"]),
        "battleGroups": watchlist_battle_groups(payload["items"]),
    }


def refresh_single_fundamental(code):
    stock = find_stock(code)
    if not stock:
        return {"ok": False, "code": code, "reason": "基础表未识别该代码。"}
    fundamental_result = fetch_ths_fundamental(
        stock["code"],
        force_refresh=True,
        wait_for_slot=True,
    )
    payload = evaluate_stock(
        stock["code"],
        refresh_fundamental=False,
        use_intraday=False,
    )
    if not fundamental_result.get("ok"):
        payload["stock"]["capacity"]["signals"].insert(1, fundamental_result.get("reason", "基本面刷新失败。"))
    return {
        "ok": True,
        "code": stock["code"],
        "name": stock.get("name"),
        "fundamentalOk": bool(fundamental_result.get("ok")),
        "fundamentalReason": fundamental_result.get("reason"),
        "fromCache": bool(fundamental_result.get("fromCache")),
        "stock": payload["stock"],
    }


def refresh_watchlist_fundamentals():
    payload = read_watchlist()
    refreshed_items = []
    results = []
    for item in payload["items"]:
        code = item.get("code")
        if not code:
            refreshed_items.append(item)
            continue
        result = refresh_single_fundamental(code)
        results.append(
            {
                "code": code,
                "name": item.get("name"),
                "ok": result.get("ok"),
                "fundamentalOk": result.get("fundamentalOk"),
                "reason": result.get("fundamentalReason") or result.get("reason"),
            }
        )
        if result.get("ok") and isinstance(result.get("stock"), dict):
            refreshed = watchlist_item_from_stock(result["stock"])
            refreshed["addedAt"] = item.get("addedAt") or now_text()
            refreshed["note"] = item.get("note", "")
            refreshed["tags"] = item.get("tags", [])
            if result.get("fundamentalReason"):
                refreshed["refreshNote"] = result["fundamentalReason"]
            refreshed_items.append(refreshed)
        else:
            item["refreshNote"] = result.get("reason") or "基本面刷新失败。"
            refreshed_items.append(item)
    write_watchlist({"items": refreshed_items})
    response = watchlist_response()
    response["refreshResults"] = results
    response["refreshedAt"] = now_text()
    return response


def refresh_watchlist_quotes(refresh_kline=False):
    payload = read_watchlist()
    cloud_quotes = None
    if (ENABLE_EASTMONEY or ENABLE_TENCENT) and not tdx_bridge_status().get("quoteCount"):
        cloud_quotes = prefetch_cloud_quotes(
            item.get("code") for item in payload.get("items", [])
        )
        if not cloud_quotes.get("ok"):
            raise RuntimeError(
                f"云端批量报价失败：{cloud_quotes.get('reason')}。保留上一版快照。"
            )
    refreshed_items = []
    results = []
    for item in payload["items"]:
        code = item.get("code")
        if not code:
            refreshed_items.append(item)
            continue
        try:
            result = evaluate_stock(
                code,
                refresh_quote=not (cloud_quotes or {}).get("ok"),
                refresh_fundamental=False,
                refresh_kline=refresh_kline,
                use_intraday=True,
            )
            stock = result.get("stock") or {}
            refreshed = watchlist_item_from_stock(stock) if stock.get("code") else None
            if refreshed:
                refreshed["addedAt"] = item.get("addedAt") or now_text()
                refreshed["note"] = item.get("note", "")
                refreshed["tags"] = item.get("tags", [])
                refreshed_items.append(refreshed)
                results.append(
                    {
                        "code": code,
                        "name": refreshed.get("name") or item.get("name"),
                        "ok": True,
                        "price": refreshed.get("lastPrice"),
                        "updatedAt": refreshed.get("lastUpdatedAt"),
                    }
                )
            else:
                refreshed_items.append(item)
                results.append({"code": code, "name": item.get("name"), "ok": False, "reason": "评估结果不可用"})
        except Exception as error:
            item["refreshNote"] = str(error)
            refreshed_items.append(item)
            results.append({"code": code, "name": item.get("name"), "ok": False, "reason": str(error)})

    write_watchlist({"items": refreshed_items})
    response = watchlist_response()
    response["refreshResults"] = results
    response["refreshedAt"] = now_text()
    return response


def refresh_home_data(refresh_kline=False, refresh_sentiment=False):
    watchlist = refresh_watchlist_quotes(refresh_kline=refresh_kline)
    sentiment = build_market_sentiment_snapshot() if refresh_sentiment else market_sentiment_status()
    sectors = build_sector_rankings()
    industry = build_industry_insight()
    daily = build_daily_brief()
    return {
        "ok": True,
        "updatedAt": now_text(),
        "watchlist": watchlist,
        "marketSentiment": sentiment,
        "sectorRankings": sectors,
        "industryInsight": industry,
        "dailyBrief": daily,
    }


def infer_market(code):
    if code in ETF_MASTER:
        return ETF_MASTER[code]["market"]
    if code.startswith(("15", "16")):
        return "深市ETF"
    if code.startswith(("51", "56", "58")):
        return "沪市ETF"
    if code.startswith("688"):
        return "科创板"
    if code.startswith(("300", "301")):
        return "创业板"
    if code.startswith(("8", "4")):
        return "北交所"
    if code.startswith("6"):
        return "沪市主板"
    if code.startswith("0"):
        return "深市主板"
    return "A股"


def find_stock(query):
    clean = query.strip().lower()
    if not clean:
        return None

    if clean in ETF_MASTER:
        return dict(ETF_MASTER[clean])

    for stock in STOCK_MASTER:
        if (
            stock["code"].lower() == clean
            or clean in stock["name"].lower()
            or clean in stock["industry"].lower()
        ):
            return stock

    if clean.isdigit() and len(clean) == 6:
        return {
            "code": clean,
            "name": f"待接入股票 {clean}",
            "market": infer_market(clean),
            "industry": infer_market(clean),
            "isST": False,
        }

    return None


def cache_path(code):
    return CACHE_DIR / f"{code}.json"


def quote_cache_path(code):
    return CACHE_DIR / f"quote_{code}.json"


def kline_cache_path(code):
    return CACHE_DIR / f"kline_{code}.json"


def fundamental_cache_path(code):
    return CACHE_DIR / f"fundamental_{code}.json"


def theme_cache_path(code):
    return CACHE_DIR / f"theme_{code}.json"


def read_market_sentiment_cache(allow_stale=False):
    if not MARKET_SENTIMENT_CACHE_PATH.exists():
        return None
    cached = load_json(MARKET_SENTIMENT_CACHE_PATH)
    if not allow_stale and time.time() - cached.get("cachedAt", 0) > MARKET_SENTIMENT_CACHE_TTL_SECONDS:
        return None
    payload = cached.get("payload")
    if isinstance(payload, dict):
        payload = normalize_market_sentiment_payload(payload)
        payload["cacheAgeSeconds"] = int(time.time() - cached.get("cachedAt", 0))
    return payload


def write_market_sentiment_cache(payload):
    with MARKET_SENTIMENT_CACHE_PATH.open("w", encoding="utf-8") as file:
        json.dump({"cachedAt": time.time(), "payload": payload}, file, ensure_ascii=False, indent=2)


def normalize_market_sentiment_payload(payload):
    if not isinstance(payload, dict) or not payload.get("ok"):
        return payload
    state = payload.get("marketState") or {}
    if state.get("positionSwitch"):
        return payload
    counts = (
        payload.get("upCount"),
        payload.get("downCount"),
        payload.get("totalCount"),
        payload.get("limitUpCount"),
        payload.get("limitDownCount"),
    )
    if all(isinstance(value, (int, float)) for value in counts):
        payload["marketState"] = classify_market_sentiment(*counts)
    return payload


def read_cache(code):
    path = cache_path(code)
    if not path.exists():
        return None
    cached = load_json(path)
    if cached.get("version") != CACHE_SCHEMA_VERSION:
        return None
    if time.time() - cached.get("cachedAt", 0) > CACHE_TTL_SECONDS:
        return None
    return cached.get("payload")


def write_cache(code, payload):
    path = cache_path(code)
    with path.open("w", encoding="utf-8") as file:
        json.dump(
            {"version": CACHE_SCHEMA_VERSION, "cachedAt": time.time(), "payload": payload},
            file,
            ensure_ascii=False,
            indent=2,
        )


def provider_status():
    state = read_provider_state()
    now = time.time()
    return {
        "name": "ths",
        "enabled": ENABLE_THS,
        "quoteCacheTtlSeconds": QUOTE_CACHE_TTL_SECONDS,
        "klineCacheTtlSeconds": KLINE_CACHE_TTL_SECONDS,
        "fundamentalCacheTtlSeconds": FUNDAMENTAL_CACHE_TTL_SECONDS,
        "themeCacheTtlSeconds": THEME_CACHE_TTL_SECONDS,
        "marketSentimentCacheTtlSeconds": MARKET_SENTIMENT_CACHE_TTL_SECONDS,
        "mainCacheTtlSeconds": CACHE_TTL_SECONDS,
        "minExternalIntervalSeconds": MIN_EXTERNAL_INTERVAL_SECONDS,
        "cooldownSeconds": PROVIDER_COOLDOWN_SECONDS,
        "blockedUntil": state.get("blockedUntil", 0),
        "blockedRemainingSeconds": max(0, int(state.get("blockedUntil", 0) - now)),
        "lastExternalAt": state.get("lastExternalAt", 0),
        "nextAllowedAt": state.get("lastExternalAt", 0) + MIN_EXTERNAL_INTERVAL_SECONDS,
        "nextAllowedRemainingSeconds": max(
            0,
            int(state.get("lastExternalAt", 0) + MIN_EXTERNAL_INTERVAL_SECONDS - now),
        ),
        "failCount": state.get("failCount", 0),
        "lastError": state.get("lastError", ""),
        "tdxBridge": tdx_bridge_status(),
        "mode": "搜索触发同花顺日K/F10" if ENABLE_THS else "安全模式：不请求外部接口",
    }


def wait_for_provider_slot(max_wait_seconds=12):
    deadline = time.time() + max_wait_seconds
    while True:
        state = read_provider_state()
        now = time.time()
        wait_seconds = max(
            0,
            state.get("blockedUntil", 0) - now,
            state.get("lastExternalAt", 0) + MIN_EXTERNAL_INTERVAL_SECONDS - now,
        )
        if wait_seconds <= 0:
            return True
        if now + wait_seconds > deadline:
            return False
        time.sleep(wait_seconds + 0.2)


def read_quote_cache(code):
    path = quote_cache_path(code)
    if not path.exists():
        return None
    cached = load_json(path)
    if time.time() - cached.get("cachedAt", 0) > QUOTE_CACHE_TTL_SECONDS:
        return None
    return cached.get("payload")


def write_quote_cache(code, quote):
    path = quote_cache_path(code)
    with path.open("w", encoding="utf-8") as file:
        json.dump({"cachedAt": time.time(), "payload": quote}, file, ensure_ascii=False, indent=2)


def bridge_quote_rows(payload):
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    rows = payload.get("quotes") or payload.get("items") or payload.get("data") or []
    if isinstance(rows, dict):
        return [dict(value, code=key) if isinstance(value, dict) else {} for key, value in rows.items()]
    return rows if isinstance(rows, list) else []


def normalize_tdx_bridge_quote(row, generated_at=None):
    if not isinstance(row, dict):
        return None
    code = normalize_security_code(row.get("code") or row.get("stockCode") or row.get("symbol"))
    price = bridge_float(row.get("price") if row.get("price") is not None else row.get("last"))
    if not code or price is None:
        return None
    quote_time = row.get("quoteTime") or row.get("date") or row.get("tradeDate")
    return {
        "source": "tdx-bridge",
        "fetchedAt": int(generated_at or time.time()),
        "code": code,
        "name": row.get("name") or row.get("stockName"),
        "price": price,
        "open": bridge_float(row.get("open")),
        "high": bridge_float(row.get("high")),
        "low": bridge_float(row.get("low")),
        "pctChange": bridge_float(row.get("pctChange") if row.get("pctChange") is not None else row.get("changePct")),
        "turnoverRate": bridge_float(row.get("turnoverRate")),
        "volume": bridge_float(row.get("volume")),
        "amount": bridge_float(row.get("amount")),
        "quoteTime": quote_time,
        "quoteClock": row.get("quoteClock") or row.get("time"),
        "previousClose": bridge_float(row.get("previousClose") if row.get("previousClose") is not None else row.get("prevClose")),
        "isIntraday": bool(row.get("isIntraday")),
    }


def read_tdx_bridge_quote(code, allow_stale=False):
    payload = safe_load_json(TDX_BRIDGE_QUOTES_PATH)
    if not payload:
        return None
    generated_at = bridge_generated_at(payload, TDX_BRIDGE_QUOTES_PATH)
    if not allow_stale and generated_at and time.time() - generated_at > TDX_BRIDGE_QUOTE_MAX_AGE_SECONDS:
        return None
    for row in bridge_quote_rows(payload):
        quote = normalize_tdx_bridge_quote(row, generated_at=generated_at)
        if quote and quote.get("code") == normalize_security_code(code):
            return quote
    return None


def normalize_tdx_bridge_kline(row):
    if not isinstance(row, dict):
        return None
    date_value = row.get("date") or row.get("tradeDate") or row.get("datetime")
    parsed_date = parse_kline_date(date_value)
    close = bridge_float(row.get("close"))
    if not parsed_date or close is None:
        return None
    return {
        "date": parsed_date.strftime("%Y%m%d"),
        "open": bridge_float(row.get("open")),
        "close": close,
        "high": bridge_float(row.get("high")),
        "low": bridge_float(row.get("low")),
        "volume": bridge_float(row.get("volume") if row.get("volume") is not None else row.get("vol")),
        "amount": bridge_float(row.get("amount")),
        "amplitude": bridge_float(row.get("amplitude")),
        "pctChange": bridge_float(row.get("pctChange") if row.get("pctChange") is not None else row.get("changePct")),
        "change": bridge_float(row.get("change")),
        "turnoverRate": bridge_float(row.get("turnoverRate")),
        "source": "tdx-bridge",
    }


def read_tdx_bridge_klines(code, period="daily", allow_stale=False):
    path = TDX_BRIDGE_KLINES_DIR / f"{normalize_security_code(code)}_{period}.json"
    payload = safe_load_json(path)
    if not payload:
        return None
    rows = payload
    if isinstance(payload, dict):
        rows = payload.get("klines") or payload.get("items") or payload.get("rows") or payload.get("data") or []
    if not isinstance(rows, list):
        return None
    klines = [normalize_tdx_bridge_kline(row) for row in rows]
    klines = sorted((row for row in klines if row), key=lambda row: row["date"])
    if len(klines) < 60:
        return None
    if not allow_stale and is_stale_kline_payload(klines):
        return None
    return klines


def read_kline_cache(code):
    path = kline_cache_path(code)
    if not path.exists():
        return None
    cached = load_json(path)
    payload = cached.get("payload")
    if is_stale_kline_payload(payload):
        return None
    cache_expired = time.time() - cached.get("cachedAt", 0) > KLINE_CACHE_TTL_SECONDS
    now = datetime.now()
    market_session = now.weekday() < 5 and (
        (now.hour == 9 and now.minute >= 15)
        or 10 <= now.hour < 15
        or (now.hour == 15 and now.minute <= 15)
    )
    if cache_expired and market_session:
        return None
    return payload


def read_kline_cache_fallback(code):
    path = kline_cache_path(code)
    if not path.exists():
        return None
    cached = load_json(path)
    payload = cached.get("payload")
    return payload if isinstance(payload, list) and len(payload) >= 60 else None


def write_kline_cache(code, klines):
    path = kline_cache_path(code)
    with path.open("w", encoding="utf-8") as file:
        json.dump({"cachedAt": time.time(), "payload": klines}, file, ensure_ascii=False, indent=2)


def parse_kline_date(value):
    text = str(value or "")
    for fmt in ("%Y%m%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def latest_expected_kline_date():
    now = datetime.now()
    candidate = now.date() if now.hour >= 18 else now.date() - timedelta(days=1)
    while candidate.weekday() >= 5 or candidate.isoformat() in MARKET_HOLIDAYS:
        candidate -= timedelta(days=1)
    return candidate


def is_stale_kline_payload(payload):
    if not isinstance(payload, list) or not payload:
        return False
    latest = parse_kline_date((payload[-1] or {}).get("date"))
    expected = latest_expected_kline_date()
    if (payload[-1] or {}).get("temporary") and len(payload) >= 2:
        base_latest = parse_kline_date((payload[-2] or {}).get("date"))
        if latest and base_latest and (latest - base_latest).days > 7:
            return True
    return bool(latest and latest < expected)


def kline_payload_gap_days(payload):
    if not isinstance(payload, list) or not payload:
        return None
    latest = parse_kline_date((payload[-1] or {}).get("date"))
    if not latest:
        return None
    return max(0, (latest_expected_kline_date() - latest).days)


def read_fundamental_cache(code):
    path = fundamental_cache_path(code)
    if not path.exists():
        return None
    cached = load_json(path)
    if time.time() - cached.get("cachedAt", 0) > FUNDAMENTAL_CACHE_TTL_SECONDS:
        return None
    return cached.get("payload")


def write_fundamental_cache(code, payload):
    path = fundamental_cache_path(code)
    with path.open("w", encoding="utf-8") as file:
        json.dump({"cachedAt": time.time(), "payload": payload}, file, ensure_ascii=False, indent=2)


def read_theme_cache(code):
    path = theme_cache_path(code)
    if not path.exists():
        return None
    cached = load_json(path)
    if time.time() - cached.get("cachedAt", 0) > THEME_CACHE_TTL_SECONDS:
        return None
    return cached.get("payload")


def write_theme_cache(code, payload):
    path = theme_cache_path(code)
    with path.open("w", encoding="utf-8") as file:
        json.dump({"cachedAt": time.time(), "payload": payload}, file, ensure_ascii=False, indent=2)


def eastmoney_secid(code):
    if code.startswith(("5", "6")):
        return f"1.{code}"
    return f"0.{code}"


def scaled(value, divisor=100):
    if value in (None, "-", ""):
        return None
    return round(float(value) / divisor, 2)


def eastmoney_price(value, code):
    divisor = 1000 if str(code).startswith(("15", "16", "51", "56", "58")) else 100
    if value in (None, "-", ""):
        return None
    decimals = 3 if divisor == 1000 else 2
    return round(float(value) / divisor, decimals)


def eastmoney_request_json(url, force=False):
    if not force and not ENABLE_EASTMONEY:
        return {
            "ok": False,
            "reason": "东财 provider 默认关闭，当前主数据源为同花顺。",
        }

    with PROVIDER_LOCK:
        state = read_provider_state()
        now = time.time()
        if state["blockedUntil"] > now:
            return {
                "ok": False,
                "reason": "东财 provider 处于熔断冷却期，暂不请求外部接口。",
            }
        if now - state["lastExternalAt"] < MIN_EXTERNAL_INTERVAL_SECONDS:
            return {
                "ok": False,
                "reason": "全局请求冷却中，避免过于频繁访问东财。",
            }

        state["lastExternalAt"] = now
        write_provider_state(state)

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 AShareScorer/0.1",
            "Accept": "application/json",
            "Referer": "https://quote.eastmoney.com/",
        },
    )

    last_error = None
    for attempt in range(max(1, PROVIDER_REQUEST_RETRIES)):
        try:
            with urllib.request.urlopen(request, timeout=8) as response:
                raw = json.loads(response.read().decode("utf-8"))
            state = read_provider_state()
            state["failCount"] = 0
            state["lastError"] = ""
            state["blockedUntil"] = 0
            write_provider_state(state)
            return {"ok": True, "data": raw}
        except (
            urllib.error.URLError,
            TimeoutError,
            ValueError,
            json.JSONDecodeError,
            http.client.RemoteDisconnected,
            http.client.IncompleteRead,
            OSError,
        ) as error:
            last_error = error
            if attempt + 1 < max(1, PROVIDER_REQUEST_RETRIES):
                time.sleep(PROVIDER_RETRY_DELAY_SECONDS * (attempt + 1))

    state = read_provider_state()
    state["failCount"] = state.get("failCount", 0) + 1
    state["lastError"] = str(last_error)
    state["blockedUntil"] = time.time() + PROVIDER_COOLDOWN_SECONDS
    write_provider_state(state)
    return {
        "ok": False,
        "reason": "东财请求失败，已进入熔断冷却，避免连续重试。",
    }


def external_request_text(url, provider_name, referer, encoding="utf-8"):
    if not ENABLE_THS:
        return {
            "ok": False,
            "reason": "同花顺日K provider 已关闭。设置 ENABLE_THS=1 后才会请求外部接口。",
        }

    with PROVIDER_LOCK:
        state = read_provider_state()
        now = time.time()
        if state["blockedUntil"] > now:
            return {
                "ok": False,
                "reason": f"{provider_name} provider 处于熔断冷却期，暂不请求外部接口。",
            }
        if now - state["lastExternalAt"] < MIN_EXTERNAL_INTERVAL_SECONDS:
            return {
                "ok": False,
                "reason": "全局请求冷却中，避免过于频繁访问行情源。",
            }

        state["lastExternalAt"] = now
        write_provider_state(state)

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 AShareScorer/0.1 Safari/537.36",
            "Accept": "*/*",
            "Referer": referer,
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            text = response.read().decode(encoding, errors="ignore")
        state = read_provider_state()
        state["failCount"] = 0
        state["lastError"] = ""
        write_provider_state(state)
        return {"ok": True, "text": text}
    except (
        urllib.error.URLError,
        TimeoutError,
        ValueError,
        http.client.RemoteDisconnected,
        http.client.IncompleteRead,
        OSError,
    ) as error:
        state = read_provider_state()
        state["failCount"] = state.get("failCount", 0) + 1
        state["lastError"] = str(error)
        state["blockedUntil"] = time.time() + PROVIDER_COOLDOWN_SECONDS
        write_provider_state(state)
        return {
            "ok": False,
            "reason": f"{provider_name} 请求失败，已进入熔断冷却，避免连续重试。",
        }


def parse_ths_number_text(value):
    text = strip_tags(value).replace(",", "").strip()
    if not text or text == "--":
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_ths_amount_text(value):
    text = strip_tags(value).replace(",", "").strip()
    if not text or text == "--":
        return None
    multiplier = 1
    if text.endswith("亿"):
        multiplier = 100_000_000
        text = text[:-1]
    elif text.endswith("万"):
        multiplier = 10_000
        text = text[:-1]
    try:
        return float(text) * multiplier
    except ValueError:
        return None


def parse_ths_market_rows(text):
    rows = []
    for row_match in re.finditer(r"<tr>(.*?)</tr>", text, re.S):
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row_match.group(1), re.S)
        if len(cells) < 11:
            continue
        rank = parse_ths_number_text(cells[0])
        code_match = re.search(r">(\d{6})<", cells[1])
        if rank is None or not code_match:
            continue
        rows.append(
            {
                "rank": int(rank),
                "code": code_match.group(1),
                "name": strip_tags(cells[2]),
                "price": parse_ths_number_text(cells[3]),
                "pctChange": parse_ths_number_text(cells[4]),
                "turnoverRate": parse_ths_number_text(cells[7]),
                "amount": parse_ths_amount_text(cells[10]),
            }
        )
    return rows


def parse_ths_market_page_count(text):
    match = re.search(r'class="page_info">(\d+)/(\d+)</span>', text)
    return int(match.group(2)) if match else None


def fetch_ths_market_page(page=1, order="desc"):
    url = f"https://q.10jqka.com.cn/index/index/field/zdf/order/{order}/page/{page}/ajax/1/"
    result = external_request_text(url, "同花顺全A情绪", "https://q.10jqka.com.cn/", encoding="gbk")
    if not result.get("ok"):
        return result
    text = result["text"]
    rows = parse_ths_market_rows(text)
    if not rows:
        return {"ok": False, "reason": "同花顺全A分页未解析到行情表。"}
    return {
        "ok": True,
        "rows": rows,
        "page": page,
        "pageCount": parse_ths_market_page_count(text),
    }


def fetch_ths_market_page_wait(page=1, order="desc"):
    while True:
        result = fetch_ths_market_page(page=page, order=order)
        reason = result.get("reason", "")
        if result.get("ok") or "全局请求冷却" not in reason:
            return result
        time.sleep(max(1, MIN_EXTERNAL_INTERVAL_SECONDS))


def fetch_ths_market_flash():
    result = external_request_text(
        "http://q.10jqka.com.cn/api.php?t=indexflash&",
        "同花顺全A情绪",
        "https://q.10jqka.com.cn/",
        encoding="gbk",
    )
    if not result.get("ok"):
        return result
    try:
        raw = json.loads(result["text"])
    except json.JSONDecodeError as error:
        return {"ok": False, "reason": f"同花顺全A情绪JSON解析失败：{error}"}

    zdfb = raw.get("zdfb_data") or {}
    zdt = raw.get("zdt_data") or {}
    jrbx = raw.get("jrbx_data") or {}
    bins = zdfb.get("zdfb") or []
    if len(bins) < 10:
        return {"ok": False, "reason": "同花顺全A情绪未返回完整涨跌分布。"}

    up_count = int(zdfb.get("znum") or sum(bins[5:]))
    down_count = int(zdfb.get("dnum") or sum(bins[:5]))
    total_count = int(sum(bins))
    flat_count = max(0, total_count - up_count - down_count)
    last_zdt = zdt.get("last_zdt") or {}
    limit_up_count = int(last_zdt.get("ztzs") or 0)
    limit_down_count = int(last_zdt.get("dtzs") or 0)
    market_state = classify_market_sentiment(up_count, down_count, total_count, limit_up_count, limit_down_count)
    snapshot = {
        "ok": True,
        "source": "ths_indexflash",
        "fetchedAt": int(time.time()),
        "totalCount": total_count,
        "upCount": up_count,
        "flatCount": flat_count,
        "downCount": down_count,
        "limitUpCount": limit_up_count,
        "limitDownCount": limit_down_count,
        "distribution": {
            "downLimitToMinus8": bins[0],
            "minus8ToMinus6": bins[1],
            "minus6ToMinus4": bins[2],
            "minus4ToMinus2": bins[3],
            "minus2ToZero": bins[4],
            "zeroTo2": bins[5],
            "twoTo4": bins[6],
            "fourTo6": bins[7],
            "sixTo8": bins[8],
            "eightToLimitUp": bins[9],
        },
        "intradayReturn": (jrbx.get("last_zdf") if isinstance(jrbx, dict) else None),
        "marketScoreRaw": raw.get("dppj_data"),
        "marketState": market_state,
        "notes": [
            "全市场情绪来自同花顺首页 indexflash 聚合接口，手动刷新一次只发起一次外部请求。",
            "冰点只作为强主线强个股回调的仓位环境，不会让弱趋势个股自动变成买点。",
            "后续可继续补微盘股指数、真实成交额和板块RPS，形成更完整的仓位开关。",
        ],
    }
    write_market_sentiment_cache(snapshot)
    return snapshot


def count_sorted_market(condition, order, page_count):
    low = 1
    high = page_count
    first_false_rank = None
    while low <= high:
        mid = (low + high) // 2
        result = fetch_ths_market_page_wait(page=mid, order=order)
        if not result.get("ok"):
            return None, result.get("reason")
        rows = result["rows"]
        if all(condition(row.get("pctChange")) for row in rows):
            low = mid + 1
        else:
            first_false = next(
                (row for row in rows if not condition(row.get("pctChange"))),
                None,
            )
            first_false_rank = first_false["rank"] if first_false else rows[-1]["rank"] + 1
            high = mid - 1
    if first_false_rank is None:
        last = fetch_ths_market_page_wait(page=page_count, order=order)
        if not last.get("ok"):
            return None, last.get("reason")
        return last["rows"][-1]["rank"], None
    return first_false_rank - 1, None


def classify_market_sentiment(up_count, down_count, total_count, limit_up_count, limit_down_count):
    traded = max(1, up_count + down_count)
    up_ratio = up_count / traded
    limit_spread = limit_up_count - limit_down_count
    if up_ratio <= 0.25:
        state = "深冰点"
        score = 86
        advice = "强主线强个股回调时，可重点看试错位；弱股不因冰点自动加分。"
        position_switch = {
            "level": "积极试错",
            "maxPosition": "20%-30%",
            "action": "只在强主线核心股回调到支撑时试错，可比正常环境更主动。",
            "reason": "全市场深度分歧时，强票回调的风险收益更容易打开，但必须保留失效位。",
        }
    elif up_ratio <= 0.35:
        state = "冰点"
        score = 76
        advice = "适合把强势主线的回调候选放到前排，但仍要等量价和失效位。"
        position_switch = {
            "level": "优先试错",
            "maxPosition": "15%-25%",
            "action": "强主线强个股可以小仓先手，确认转强后再加。",
            "reason": "冰点提供的是低吸窗口，不是无条件买入信号。",
        }
    elif up_ratio >= 0.75:
        state = "过热"
        score = 35
        advice = "市场偏热时不追高，已有底仓更适合等分歧回踩后再加。"
        position_switch = {
            "level": "降低新开仓",
            "maxPosition": "0%-10%",
            "action": "不追涨开新仓，已有底仓以持有和等待分歧为主。",
            "reason": "上涨家数过多时容易进入一致性阶段，次日分化风险更高。",
        }
    elif up_ratio >= 0.62 and limit_spread > 20:
        state = "偏强"
        score = 65
        advice = "情绪支持趋势延续，但追涨性价比一般，优先找缩量回踩。"
        position_switch = {
            "level": "正常偏积极",
            "maxPosition": "10%-20%",
            "action": "按计划做强股回调，不因为情绪偏强去追高。",
            "reason": "涨停扩散说明风险偏好尚可，但好买点仍来自回调和量价确认。",
        }
    else:
        state = "正常"
        score = 55
        advice = "情绪不提供明显仓位加成，按个股趋势、主线和买点执行。"
        position_switch = {
            "level": "正常执行",
            "maxPosition": "10%-15%",
            "action": "按个股买点和板块强度执行，不额外放大仓位。",
            "reason": "市场没有明显冰点或过热，胜率主要由主线、RPS和个股结构决定。",
        }
    if total_count and (limit_down_count / total_count) >= 0.015:
        advice += " 跌停占比偏高时，仓位仍要收着。"
        position_switch["level"] = "风控优先"
        position_switch["maxPosition"] = "0%-10%"
        position_switch["action"] = "跌停风险偏高，除核心强票低吸外，降低新开仓。"
        position_switch["reason"] += " 同时跌停占比偏高，说明亏钱效应仍在扩散。"
    return {
        "state": state,
        "score": score,
        "advice": advice,
        "upRatio": round(up_ratio * 100, 1),
        "positionSwitch": position_switch,
    }


def build_market_sentiment_snapshot():
    flash = fetch_ths_market_flash()
    if flash.get("ok"):
        return flash

    first = fetch_ths_market_page_wait(page=1, order="desc")
    if not first.get("ok"):
        return {"ok": False, "reason": first.get("reason", "同花顺全A首页读取失败。")}
    page_count = first.get("pageCount")
    if not page_count:
        return {"ok": False, "reason": "同花顺全A分页数解析失败。"}

    last = fetch_ths_market_page_wait(page=page_count, order="desc")
    if not last.get("ok"):
        return {"ok": False, "reason": last.get("reason", "同花顺全A尾页读取失败。")}
    total_count = last["rows"][-1]["rank"]

    up_count, reason = count_sorted_market(lambda value: value is not None and value > 0, "desc", page_count)
    if up_count is None:
        return {"ok": False, "reason": reason}
    non_down_count, reason = count_sorted_market(lambda value: value is not None and value >= 0, "desc", page_count)
    if non_down_count is None:
        return {"ok": False, "reason": reason}
    limit_up_count, reason = count_sorted_market(lambda value: value is not None and value >= 9.8, "desc", page_count)
    if limit_up_count is None:
        return {"ok": False, "reason": reason}
    limit_down_count, reason = count_sorted_market(lambda value: value is not None and value <= -9.8, "asc", page_count)
    if limit_down_count is None:
        return {"ok": False, "reason": reason}

    flat_count = max(0, non_down_count - up_count)
    down_count = max(0, total_count - non_down_count)
    amount_values = [row.get("amount") for row in first["rows"] if row.get("amount") is not None]
    top_amount = sum(amount_values) if amount_values else None
    market_state = classify_market_sentiment(up_count, down_count, total_count, limit_up_count, limit_down_count)
    snapshot = {
        "ok": True,
        "source": "ths_market_pages",
        "fetchedAt": int(time.time()),
        "totalCount": total_count,
        "upCount": up_count,
        "flatCount": flat_count,
        "downCount": down_count,
        "limitUpCount": limit_up_count,
        "limitDownCount": limit_down_count,
        "topPageAmount": round(top_amount, 0) if top_amount is not None else None,
        "topGainers": first["rows"][:5],
        "marketState": market_state,
        "notes": [
            "全市场情绪通过同花顺A股涨跌幅排序分页低频推算，刷新任务会按全局冷却间隔串行请求。",
            "成交额第一版只展示涨幅第一页合计，不把它当作全市场总成交额。",
            "冰点只作为强主线强个股回调的仓位环境，不会让弱趋势个股自动变成买点。",
        ],
    }
    write_market_sentiment_cache(snapshot)
    return snapshot


def refresh_market_sentiment_background():
    global MARKET_SENTIMENT_REFRESHING
    with MARKET_SENTIMENT_LOCK:
        if MARKET_SENTIMENT_REFRESHING:
            return
        MARKET_SENTIMENT_REFRESHING = True
    try:
        build_market_sentiment_snapshot()
    finally:
        with MARKET_SENTIMENT_LOCK:
            MARKET_SENTIMENT_REFRESHING = False


def market_sentiment_status(refresh=False):
    cached = read_market_sentiment_cache(allow_stale=True)
    fresh = read_market_sentiment_cache(allow_stale=False)
    if refresh and not MARKET_SENTIMENT_REFRESHING:
        threading.Thread(target=refresh_market_sentiment_background, daemon=True).start()
    if fresh:
        fresh["refreshing"] = MARKET_SENTIMENT_REFRESHING
        fresh["cacheTtlSeconds"] = MARKET_SENTIMENT_CACHE_TTL_SECONDS
        return fresh
    if cached:
        cached["ok"] = True
        cached["stale"] = True
        cached["refreshing"] = MARKET_SENTIMENT_REFRESHING
        cached["cacheTtlSeconds"] = MARKET_SENTIMENT_CACHE_TTL_SECONDS
        return cached
    return {
        "ok": False,
        "refreshing": MARKET_SENTIMENT_REFRESHING,
        "cacheTtlSeconds": MARKET_SENTIMENT_CACHE_TTL_SECONDS,
        "reason": "全市场情绪尚未刷新。点击刷新后会后台低频读取同花顺聚合接口并写入本地缓存。",
    }


def market_sentiment_signal(sentiment):
    if not sentiment or not sentiment.get("ok"):
        return "全市场情绪尚未刷新，当前评分不使用情绪仓位开关。"
    state = (sentiment.get("marketState") or {}).get("state") or "待确认"
    up_ratio = (sentiment.get("marketState") or {}).get("upRatio")
    advice = (sentiment.get("marketState") or {}).get("advice") or ""
    ratio_text = f"，上涨占比 {up_ratio:.1f}%" if isinstance(up_ratio, (int, float)) else ""
    return f"全市场情绪：{state}{ratio_text}；涨/平/跌 {sentiment.get('upCount')}/{sentiment.get('flatCount')}/{sentiment.get('downCount')}，涨停/跌停 {sentiment.get('limitUpCount')}/{sentiment.get('limitDownCount')}。{advice}"


THEME_GROUP_RULES = [
    ("电子元件/晶振", ("晶振", "石英晶体", "谐振器", "振荡器", "频控", "电子元件", "元件")),
    ("CPO/光模块", ("cpo", "共封装光学", "光模块", "光通信", "光芯片", "光器件")),
    ("半导体/先进封装", ("半导体", "芯片", "存储芯片", "集成电路", "晶圆", "光刻", "eda", "第三代半导体", "先进封装", "封测", "封装")),
    ("PCB/载板", ("pcb", "印制电路", "覆铜板", "封装基板", "载板")),
    ("算力/数据中心", ("算力", "服务器", "数据中心", "液冷", "英伟达", "ai", "ict")),
    ("机器人", ("机器人", "减速器", "工业自动化", "伺服", "人形")),
    ("低空/军工", ("低空", "无人机", "卫星", "军工", "航空", "航天")),
    ("新能源", ("新能源", "动力电池", "锂电", "储能", "光伏", "逆变器", "电网")),
    ("消费电子", ("消费电子", "智能穿戴", "苹果概念", "手机产业链", "折叠屏")),
]


def mainline_theme_group(text):
    clean = (text or "").lower()
    scored = []
    for index, (group, keywords) in enumerate(THEME_GROUP_RULES):
        score = sum(1 for keyword in keywords if keyword.lower() in clean)
        if score:
            scored.append((score, -index, group))
    if not scored:
        return "未匹配"
    return max(scored)[2]


def stock_theme_text(stock, theme):
    parts = [
        stock.get("industry"),
        stock.get("name"),
        (theme or {}).get("industry"),
        (theme or {}).get("limitUpReason"),
        (theme or {}).get("coreView"),
        " ".join((theme or {}).get("concepts") or []),
    ]
    return " ".join(part for part in parts if part)


def load_mainline_sample_rows():
    for path in [*CLASSIFIED_SAMPLE_PATHS, MAINLINE_SAMPLE_PATH]:
        if not path.exists():
            continue
        try:
            rows = load_json(path)
        except (OSError, json.JSONDecodeError):
            continue
        if rows:
            return rows
    return []


def read_cached_ths_klines_any_age(code):
    bridged = read_tdx_bridge_klines(code, allow_stale=True)
    if bridged:
        return bridged
    path = kline_cache_path(f"ths_{code}")
    if not path.exists():
        return None
    try:
        cached = load_json(path)
    except (OSError, json.JSONDecodeError):
        return None
    payload = cached.get("payload")
    return payload if isinstance(payload, list) and len(payload) >= 60 else None


def window_return(klines, window):
    if not klines or len(klines) <= window:
        return None
    latest = klines[-1].get("close")
    base = klines[-1 - window].get("close")
    if latest is None or not base:
        return None
    return latest / base - 1


def percentile_rank_for_key(values, key):
    clean = {item_key: value for item_key, value in values.items() if value is not None}
    if key not in clean or not clean:
        return None
    ordered = sorted(clean.items(), key=lambda item: item[1])
    if len(ordered) == 1:
        return 100.0
    for index, (item_key, _) in enumerate(ordered):
        if item_key == key:
            return index / (len(ordered) - 1) * 100
    return None


def sample_group(sample_theme):
    return mainline_theme_group(sample_theme) if sample_theme else "未匹配"


def theme_group_from_row(row):
    priority_parts = [
        row.get("sampleTheme"),
        row.get("coreView"),
        row.get("limitUpReason"),
        row.get("industryGroup"),
        row.get("industry"),
        " ".join(row.get("topConcepts") or []),
    ]
    for part in priority_parts:
        group = mainline_theme_group(str(part or ""))
        if group != "未匹配":
            return group
    return row.get("industryGroup") or sample_group(row.get("sampleTheme"))


def row_strength_group(row):
    return theme_group_from_row(row)


def current_strength_group(stock, theme, sample_rows):
    match = next((row for row in sample_rows if row.get("code") == stock.get("code")), None)
    if match:
        group = theme_group_from_row(match)
        if group and group != "未匹配":
            return group
    theme_text = stock_theme_text(stock, theme)
    group = mainline_theme_group(theme_text)
    if group != "未匹配":
        return group
    industry = (theme or {}).get("industry") or stock.get("industry")
    return re.sub(r"[ⅠⅡⅢⅣⅤ]+$", "", str(industry or "").strip()) or "未匹配"


def group_return(stocks, window):
    values = [window_return(item["klines"], window) for item in stocks]
    clean = [value for value in values if value is not None]
    return average(clean)


def group_amount_ratio(stocks):
    by_offset = []
    max_len = max((len(item["klines"]) for item in stocks), default=0)
    for offset in range(min(20, max_len)):
        total = 0
        has_value = False
        for stock in stocks:
            if len(stock["klines"]) <= offset:
                continue
            amount = stock["klines"][-1 - offset].get("amount")
            if amount:
                total += amount
                has_value = True
        if has_value:
            by_offset.append(total)
    if len(by_offset) < 5 or not by_offset[0]:
        return None
    base = average(by_offset)
    return by_offset[0] / base if base else None


def group_above_ma_ratio(stocks, window=20):
    states = []
    for stock in stocks:
        closes = [row.get("close") for row in stock["klines"] if row.get("close") is not None]
        if len(closes) < window:
            continue
        baseline = average(closes[-window:])
        if baseline:
            states.append(closes[-1] > baseline)
    return sum(states) / len(states) if states else None


def group_positive_ratio(stocks, window=5):
    states = []
    for stock in stocks:
        value = window_return(stock["klines"], window)
        if value is not None:
            states.append(value > 0)
    return sum(states) / len(states) if states else None


def clamp(value, low=0, high=100):
    return max(low, min(high, value))


def group_quality_view(group_rps, red80, group_size, above_ma20, positive_5):
    rps5 = group_rps.get("groupRps5") or 0
    rps10 = group_rps.get("groupRps10") or 0
    rps20 = group_rps.get("groupRps20") or 0
    rps50 = group_rps.get("groupRps50") or 0
    amount = group_rps.get("groupAmountRatio20")
    above = above_ma20 if above_ma20 is not None else 0
    positive = positive_5 if positive_5 is not None else 0

    rps_composite = rps5 * 0.12 + rps10 * 0.18 + rps20 * 0.38 + rps50 * 0.32
    breadth_score = (above * 62) + (positive * 38)
    if amount is None:
        amount_score = 45
    elif 0.95 <= amount <= 1.45:
        amount_score = 88
    elif 0.75 <= amount < 0.95:
        amount_score = 68
    elif 1.45 < amount <= 1.85:
        amount_score = 72
    else:
        amount_score = 48

    flags = []
    penalty = 0
    if group_size < 8:
        flags.append("样本偏少，排名容易跳动")
        penalty += 6
    if rps5 >= 85 and rps20 < 65:
        flags.append("短线脉冲，20日强度未跟上")
        penalty += 12
    if rps50 >= 80 and rps20 <= rps50 - 14:
        flags.append("中期仍强，但20日强度钝化")
        penalty += 10
    if rps20 >= 75 and above < 0.50:
        flags.append("RPS强但站上MA20比例不足")
        penalty += 12
    if rps20 >= 75 and positive < 0.45:
        flags.append("RPS强但近5日上涨家数不足")
        penalty += 10
    if amount is not None and amount >= 1.45 and positive < 0.55:
        flags.append("放量但扩散不足，可能是量化拉抬")
        penalty += 10
    if red80 <= 1 and rps5 >= 80:
        flags.append("只有短线红线，持续性待验证")
        penalty += 8

    score = clamp(rps_composite * 0.46 + breadth_score * 0.34 + amount_score * 0.12 + (red80 / 4 * 100) * 0.08 - penalty, 0, 100)
    if score >= 78 and penalty <= 8:
        label = "主线质量高"
        level = "high"
    elif score >= 62 and penalty <= 18:
        label = "质量尚可"
        level = "medium"
    elif penalty >= 22:
        label = "强度失真"
        level = "distorted"
    else:
        label = "质量待确认"
        level = "watch"

    return {
        "score": round(score, 1),
        "rpsComposite": round(rps_composite, 1),
        "breadthScore": round(breadth_score, 1),
        "amountScore": round(amount_score, 1),
        "penalty": round(penalty, 1),
        "label": label,
        "level": level,
        "flags": flags[:4],
    }


def classify_group_state(group_rps, red80, group_size, above_ma20, positive_5):
    rps5 = group_rps.get("groupRps5")
    rps20 = group_rps.get("groupRps20")
    amount = group_rps.get("groupAmountRatio20")
    reliable = group_size >= 5

    if not reliable:
        trend = "样本不足"
    elif red80 >= 3 and (rps20 or 0) >= 70 and (above_ma20 or 0) >= 0.60:
        trend = "主升"
    elif (rps20 or 0) >= 60 and (above_ma20 or 0) >= 0.55:
        trend = "上升"
    elif (rps20 or 0) < 40 or (above_ma20 is not None and above_ma20 < 0.40):
        trend = "退潮"
    else:
        trend = "震荡"

    if not reliable:
        heat = "样本不足"
    elif (rps5 or 0) >= 80 and (amount or 0) >= 1.15 and (positive_5 or 0) >= 0.60:
        heat = "高热"
    elif (rps5 or 0) >= 65 and (positive_5 or 0) >= 0.55:
        heat = "升温"
    elif (rps5 or 0) < 40 or (positive_5 is not None and positive_5 < 0.40):
        heat = "降温"
    else:
        heat = "平稳"

    if trend in ("主升", "上升") and heat != "降温":
        gate = "允许加权"
        reason = "板块趋势向上且热度未退潮，可以提高强股的入池优先级。"
    elif trend == "退潮" or heat == "降温":
        gate = "禁止加权"
        reason = "板块处于退潮或降温状态，个股即使强也不因板块获得额外加分。"
    else:
        gate = "谨慎观察"
        reason = "板块趋势或热度尚未形成共振，暂不放大仓位。"
    return {
        "trend": trend,
        "heat": heat,
        "gate": gate,
        "reason": reason,
        "reliable": reliable,
        "aboveMa20Ratio": round(above_ma20 * 100, 1) if above_ma20 is not None else None,
        "positive5Ratio": round(positive_5 * 100, 1) if positive_5 is not None else None,
    }


def build_sector_thesis(group_rps, red80, group_size, above_ma20, positive_5):
    if group_size < 5:
        return {
            "phase": "样本不足",
            "breadth": "暂不判断",
            "action": "只看个股",
            "reason": "同组样本少于5只，板块阶段容易失真，暂不据此提高仓位。",
            "available": False,
        }

    rps5 = group_rps.get("groupRps5")
    rps20 = group_rps.get("groupRps20")
    rps50 = group_rps.get("groupRps50")
    amount = group_rps.get("groupAmountRatio20")
    above = above_ma20 or 0
    positive = positive_5 or 0

    if (rps20 or 0) >= 80 and (rps50 or 0) >= 70 and above >= 0.60:
        phase = "持续主线"
    elif (rps5 or 0) >= 80 and (rps20 or 0) >= 60 and (rps5 or 0) >= (rps20 or 0) + 8:
        phase = "新晋增强"
    elif (rps20 or 0) >= 75 and ((rps5 or 0) < 55 or positive < 0.45):
        phase = "高位分化"
    elif (rps5 or 0) >= 65 and (rps20 or 0) < 55:
        phase = "弱反弹"
    elif (rps20 or 0) < 40 or above < 0.40:
        phase = "退潮"
    else:
        phase = "震荡蓄势"

    if above >= 0.65 and positive >= 0.60 and red80 >= 2:
        breadth = "扩散健康"
    elif red80 >= 2 and above < 0.50:
        breadth = "核心抱团"
    elif positive >= 0.65 and red80 < 2:
        breadth = "普涨修复"
    elif above < 0.40 or positive < 0.40:
        breadth = "参与不足"
    else:
        breadth = "分化一般"

    if phase in ("持续主线", "新晋增强") and breadth == "扩散健康":
        action = "回调优先"
        reason = "板块中期强度、短期动量和内部扩散同时成立，优先等待核心股缩量回调。"
    elif phase in ("持续主线", "高位分化") and breadth == "核心抱团":
        action = "只做核心"
        reason = "板块仍有强度但上涨集中在少数核心股，不适合向后排扩散或追涨。"
    elif phase == "震荡蓄势" and (amount or 0) >= 1:
        action = "等待突破"
        reason = "板块尚未形成明确主升，但成交额没有明显退去，等待RPS与扩散同步转强。"
    elif phase in ("弱反弹", "退潮") or breadth == "参与不足":
        action = "回避加仓"
        reason = "板块持续性或内部参与度不足，个股反弹暂不视为主线回调机会。"
    else:
        action = "谨慎观察"
        reason = "板块信号尚未共振，只保留核心股观察，不因单日上涨提高仓位。"

    return {
        "phase": phase,
        "breadth": breadth,
        "action": action,
        "reason": reason,
        "available": True,
    }


def build_stage_top_risk(group_rps, group_size, above_ma20, positive_5):
    if group_size < 5:
        return {
            "label": "样本不足",
            "level": "unknown",
            "count": 0,
            "signals": ["同组样本少于5只，阶段顶部风险暂不判断。"],
            "available": False,
        }

    rps5 = group_rps.get("groupRps5")
    rps20 = group_rps.get("groupRps20")
    rps50 = group_rps.get("groupRps50")
    amount = group_rps.get("groupAmountRatio20")
    above = above_ma20 if above_ma20 is not None else 0
    positive = positive_5 if positive_5 is not None else 0

    checks = []
    if rps50 is not None and rps20 is not None and rps50 >= 80 and rps20 <= rps50 - 8:
        checks.append("强度钝化：中期RPS仍高，但20日RPS明显低于50日RPS。")
    elif rps20 is not None and rps5 is not None and rps20 >= 75 and rps5 <= rps20 - 12:
        checks.append("强度钝化：板块仍强，但5日RPS已经明显掉队。")

    if rps20 is not None and rps20 >= 70 and (above < 0.55 or positive < 0.45):
        checks.append("扩散变差：板块RPS仍强，但站上MA20或近5日上涨的个股比例不足。")

    if amount is not None and amount >= 1.25 and positive < 0.50:
        checks.append("量价背离：板块成交额放大，但上涨家数没有同步扩散。")
    elif amount is not None and amount < 0.90 and rps20 is not None and rps20 >= 75:
        checks.append("量价背离：板块强度仍在，但成交额已经低于均值。")

    if above < 0.45 and rps20 is not None and rps20 >= 60:
        checks.append("关键位失守：板块仍有热度，但MA20上方比例已低于45%。")
    elif rps50 is not None and rps50 >= 75 and rps20 is not None and rps20 < 60:
        checks.append("关键位失守：中期强势板块的20日RPS已回落到60以下。")

    count = len(checks)
    if count >= 3:
        label = "阶段顶部风险"
        level = "high"
        advice = "不追高，降低后排仓位，只等核心股回踩支撑后的试错机会。"
    elif count == 2:
        label = "高位分歧"
        level = "medium"
        advice = "主线未否定，但新增仓位要等缩量回调和重新转强。"
    elif count == 1:
        label = "偏热观察"
        level = "watch"
        advice = "只出现单项风险，先观察修复情况，不直接判顶。"
    else:
        label = "顶部未确认"
        level = "low"
        advice = "未出现足够的阶段顶部证据，按趋势回调框架处理。"

    return {
        "label": label,
        "level": level,
        "count": count,
        "signals": checks + [advice],
        "available": True,
    }


def strength_label(value, strong=80, lead=90):
    if value is None:
        return "待接入"
    if value >= lead:
        return "领涨"
    if value >= strong:
        return "强势"
    if value >= 60:
        return "偏强"
    if value >= 40:
        return "中性"
    return "偏弱"


def strength_priority(verdict, stock_rps, group_rps, red80, group_state):
    rps50 = stock_rps.get("rps50")
    amount_ratio = group_rps.get("groupAmountRatio20")
    gate = (group_state or {}).get("gate")
    if verdict == "强股强方向" and gate == "允许加权" and amount_ratio is not None and amount_ratio >= 1:
        return {
            "level": "A",
            "label": "优先入池",
            "reason": "个股RPS、板块趋势和热度共振，且方向成交额不弱，适合优先等待回调买点。",
        }
    if verdict == "强股强方向" and gate == "允许加权":
        return {
            "level": "A-",
            "label": "优先观察",
            "reason": "个股与板块趋势共振，但方向量能未明显放大，适合优先观察。",
        }
    if verdict == "强股强方向":
        return {
            "level": "B+",
            "label": "强股观察",
            "reason": f"个股和板块RPS较强，但板块状态为{gate or '待确认'}，不提升到A档。",
        }
    if verdict == "个股强于方向":
        return {
            "level": "B+",
            "label": "个股观察",
            "reason": "个股相对强，但方向没有形成多周期红线，仓位应低于强股强方向。",
        }
    if verdict == "方向强，个股待确认":
        return {
            "level": "B",
            "label": "方向观察",
            "reason": "方向较强但个股RPS未确认，优先等个股重新转强。",
        }
    if rps50 is not None and rps50 < 40 and red80 == 0:
        return {
            "level": "C",
            "label": "暂缓入池",
            "reason": "个股RPS偏弱且方向红线不足，容易出现分数虚高但胜率不足。",
        }
    return {
        "level": "B-",
        "label": "普通观察",
        "reason": "强度证据不足，先按普通趋势回调处理，不提高优先级。",
    }


def build_strength_view(stock, klines, theme):
    sample_rows = load_mainline_sample_rows()
    dataset = []
    for row in sample_rows:
        cached_klines = read_cached_ths_klines_any_age(row.get("code"))
        if not cached_klines:
            continue
        dataset.append(
            {
                "code": row["code"],
                "name": row.get("name") or row["code"],
                "group": row_strength_group(row),
                "klines": cached_klines,
            }
        )

    current_code = stock["code"]
    current_group = current_strength_group(stock, theme, sample_rows)
    dataset = [item for item in dataset if item["code"] != current_code]
    dataset.append(
        {
            "code": current_code,
            "name": stock.get("name") or current_code,
            "group": current_group,
            "klines": klines,
        }
    )

    if len(dataset) < 20:
        return {
            "available": False,
            "signals": ["本地RPS样本不足，暂不生成主线强度。"],
        }

    stock_rps = {}
    for window in (20, 50, 120):
        values = {item["code"]: window_return(item["klines"], window) for item in dataset}
        rank = percentile_rank_for_key(values, current_code)
        stock_rps[f"rps{window}"] = round(rank, 1) if rank is not None else None
        stock_rps[f"return{window}"] = round((values.get(current_code) or 0) * 100, 1) if values.get(current_code) is not None else None

    groups = {}
    for item in dataset:
        groups.setdefault(item["group"], []).append(item)
    group_rps = {}
    current_group_size = len(groups.get(current_group, []))
    for window in (5, 10, 20, 50):
        values = {group: group_return(items, window) for group, items in groups.items()}
        rank = percentile_rank_for_key(values, current_group)
        group_rps[f"groupRps{window}"] = round(rank, 1) if rank is not None else None
        group_rps[f"groupReturn{window}"] = round((values.get(current_group) or 0) * 100, 1) if values.get(current_group) is not None else None
    amount_ratio = group_amount_ratio(groups.get(current_group, []))
    group_rps["groupAmountRatio20"] = round(amount_ratio, 2) if amount_ratio is not None else None
    above_ma20 = group_above_ma_ratio(groups.get(current_group, []))
    positive_5 = group_positive_ratio(groups.get(current_group, []), 5)

    group_values = [group_rps.get(f"groupRps{window}") for window in (5, 10, 20, 50)]
    red80 = sum(value is not None and value >= 80 for value in group_values)
    red90 = sum(value is not None and value >= 90 for value in group_values)
    stock_lead = stock_rps.get("rps50") is not None and stock_rps["rps50"] >= 80
    group_lead = red80 >= 3 or red90 >= 2
    if stock_lead and group_lead:
        verdict = "强股强方向"
    elif stock_lead:
        verdict = "个股强于方向"
    elif group_lead:
        verdict = "方向强，个股待确认"
    else:
        verdict = "强度待确认"
    group_state = classify_group_state(group_rps, red80, current_group_size, above_ma20, positive_5)
    quality = group_quality_view(group_rps, red80, current_group_size, above_ma20, positive_5)
    sector_thesis = build_sector_thesis(
        group_rps,
        red80,
        current_group_size,
        above_ma20,
        positive_5,
    )
    stage_top_risk = build_stage_top_risk(
        group_rps,
        current_group_size,
        above_ma20,
        positive_5,
    )
    priority = strength_priority(verdict, stock_rps, group_rps, red80, group_state)

    signals = [
        f"个股RPS50 {format_strength_value(stock_rps.get('rps50'))}，{strength_label(stock_rps.get('rps50'))}；RPS20 {format_strength_value(stock_rps.get('rps20'))}。",
        f"匹配方向：{current_group}，样本内同组 {current_group_size} 只。",
        f"板块RPS红线：>=80 有 {red80}/4 条，>=90 有 {red90}/4 条。",
        f"板块趋势 {group_state['trend']}，热度 {group_state['heat']}；{group_state['reason']}",
        f"主线质量 {quality['label']}，质量分 {quality['score']}；{('；'.join(quality['flags']) if quality['flags'] else '未发现明显RPS失真。')}",
        f"板块阶段 {sector_thesis['phase']}，扩散质量 {sector_thesis['breadth']}；{sector_thesis['reason']}",
        f"阶段顶部风险：{stage_top_risk['label']}，命中 {stage_top_risk['count']}/4 项；{'；'.join(stage_top_risk['signals'])}",
    ]
    if group_rps.get("groupAmountRatio20") is not None:
        signals.append(f"方向成交额相对20日均值 {group_rps['groupAmountRatio20']:.2f}x。")
    signals.append(
        f"当前RPS基于本地{len(dataset)}只可计算样本，目标样本{len(sample_rows)}只；"
        "仅使用已有K线与行业缓存，不新增外部请求。"
    )

    return {
        "available": True,
        "verdict": verdict,
        "group": current_group,
        "sampleSize": len(dataset),
        "sampleUniverseSize": len(sample_rows),
        "groupSize": current_group_size,
        "stockRps": stock_rps,
        "groupRps": group_rps,
        "groupRed80": red80,
        "groupRed90": red90,
        "groupState": group_state,
        "quality": quality,
        "sectorThesis": sector_thesis,
        "stageTopRisk": stage_top_risk,
        "priority": priority,
        "signals": signals,
    }


def build_sector_rankings(limit=16):
    sample_rows = load_mainline_sample_rows()
    dataset = []
    for row in sample_rows:
        code = row.get("code")
        cached_klines = read_cached_ths_klines_any_age(code)
        if not code or not cached_klines:
            continue
        group = row_strength_group(row)
        if not group or group == "未匹配":
            continue
        dataset.append(
            {
                "code": code,
                "name": row.get("name") or code,
                "group": group,
                "industry": row.get("industry") or row.get("industryGroup") or group,
                "klines": cached_klines,
            }
        )

    groups = {}
    for item in dataset:
        groups.setdefault(item["group"], []).append(item)

    reliable_groups = {
        group: items
        for group, items in groups.items()
        if len(items) >= 5
    }
    if len(reliable_groups) < 3:
        return {
            "ok": False,
            "updatedAt": now_text(),
            "sampleSize": len(dataset),
            "groupSize": len(reliable_groups),
            "items": [],
            "reason": "可计算板块样本不足，暂不生成热门板块排行。",
        }

    returns_by_window = {
        window: {
            group: group_return(items, window)
            for group, items in reliable_groups.items()
        }
        for window in (5, 10, 20, 50)
    }

    items = []
    for group, stocks in reliable_groups.items():
        group_rps = {}
        for window in (5, 10, 20, 50):
            rank = percentile_rank_for_key(returns_by_window[window], group)
            group_rps[f"groupRps{window}"] = round(rank, 1) if rank is not None else None
            value = returns_by_window[window].get(group)
            group_rps[f"groupReturn{window}"] = round(value * 100, 1) if value is not None else None

        amount_ratio = group_amount_ratio(stocks)
        above_ma20 = group_above_ma_ratio(stocks)
        positive_5 = group_positive_ratio(stocks, 5)
        group_rps["groupAmountRatio20"] = round(amount_ratio, 2) if amount_ratio is not None else None

        group_values = [group_rps.get(f"groupRps{window}") for window in (5, 10, 20, 50)]
        red80 = sum(value is not None and value >= 80 for value in group_values)
        red90 = sum(value is not None and value >= 90 for value in group_values)
        state = classify_group_state(group_rps, red80, len(stocks), above_ma20, positive_5)
        quality = group_quality_view(group_rps, red80, len(stocks), above_ma20, positive_5)
        thesis = build_sector_thesis(group_rps, red80, len(stocks), above_ma20, positive_5)
        risk = build_stage_top_risk(group_rps, len(stocks), above_ma20, positive_5)

        score = quality["score"]

        ranked_stocks = sorted(
            stocks,
            key=lambda item: window_return(item["klines"], 20) if window_return(item["klines"], 20) is not None else -999,
            reverse=True,
        )
        leaders = [
            {
                "code": item["code"],
                "name": item["name"],
                "return20": round((window_return(item["klines"], 20) or 0) * 100, 1),
                "return50": round((window_return(item["klines"], 50) or 0) * 100, 1),
            }
            for item in ranked_stocks[:5]
        ]

        items.append(
            {
                "group": group,
                "score": score,
                "tradeAction": thesis.get("action") or state.get("gate") or "观察",
                "stageLabel": thesis.get("phase") or state.get("trend") or "待确认",
                "heatLabel": state.get("heat"),
                "sampleSize": len(stocks),
                "groupRps": group_rps,
                "groupRed80": red80,
                "groupRed90": red90,
                "state": state,
                "quality": quality,
                "thesis": thesis,
                "risk": risk,
                "aboveMa20Ratio": round(above_ma20 * 100, 1) if above_ma20 is not None else None,
                "positive5Ratio": round(positive_5 * 100, 1) if positive_5 is not None else None,
                "amountRatio20": round(amount_ratio, 2) if amount_ratio is not None else None,
                "leaders": leaders,
            }
        )

    items.sort(key=lambda item: item["score"], reverse=True)
    action_order = ["回调优先", "只做核心", "等待突破", "谨慎观察", "回避加仓"]
    action_groups = []
    for action in action_order:
        matched = [item for item in items if item.get("tradeAction") == action]
        action_groups.append(
            {
                "key": action,
                "count": len(matched),
                "groups": [item["group"] for item in matched[:5]],
            }
        )
    return {
        "ok": True,
        "updatedAt": now_text(),
        "sampleSize": len(dataset),
        "groupSize": len(reliable_groups),
        "actionGroups": action_groups,
        "items": items[:limit],
    }


INDUSTRY_CHAIN_RULES = [
    {
        "key": "半导体国产替代",
        "keywords": ("半导体", "先进封装", "光刻", "芯片", "晶振", "PCB", "载板", "硅", "存储", "设备", "材料"),
        "logic": "设备/材料先看替代空间，设计/封测再看订单兑现，链条强度要由上游扩散到核心股。",
    },
    {
        "key": "AI算力与通信",
        "keywords": ("CPO", "光模块", "算力", "服务器", "液冷", "交换机", "通信", "数据中心", "PCB"),
        "logic": "先看海外算力景气和订单，再看光模块、PCB、液冷是否轮动共振。",
    },
    {
        "key": "消费电子与端侧AI",
        "keywords": ("消费电子", "手机", "苹果", "折叠屏", "智能穿戴", "AI眼镜", "端侧", "光学光电子"),
        "logic": "先确认新品周期和库存去化，再看零部件是否从题材扩散到业绩线。",
    },
    {
        "key": "新能源与电池",
        "keywords": ("新能源", "电池", "储能", "光伏", "风电", "能源金属", "锂电"),
        "logic": "先看需求修复和价格拐点，再看材料、电池、设备之间是否形成扩散。",
    },
    {
        "key": "军工航天",
        "keywords": ("军工", "卫星", "航天", "低空", "航空", "北斗", "无人机"),
        "logic": "主题弹性强，但需要订单、型号、交付节奏补证，反弹到压力位先看承接。",
    },
    {
        "key": "资源与贵金属",
        "keywords": ("黄金", "铜", "铝", "锂", "稀土", "有色", "煤炭", "油气", "矿", "小金属"),
        "logic": "资源线核心变量是商品价格和供给约束，强趋势中更适合等回踩而不是追高。",
    },
    {
        "key": "金融与红利",
        "keywords": ("证券", "银行", "保险", "红利", "中字头", "央企"),
        "logic": "金融红利更多看指数环境和资金风格，强度不足时不扩到后排。",
    },
]


def industry_chain_for_group(group):
    text = str(group or "")
    for chain in INDUSTRY_CHAIN_RULES:
        if any(keyword in text for keyword in chain["keywords"]):
            return chain
    return {
        "key": "其他活跃题材",
        "keywords": (),
        "logic": "先观察是否能连续进入强度排行，再决定是否纳入主线。",
    }


def build_industry_insight():
    ranking = build_sector_rankings(limit=80)
    if not ranking.get("ok"):
        return {
            "ok": False,
            "updatedAt": now_text(),
            "reason": ranking.get("reason") or "板块样本不足。",
            "chains": [],
        }

    chains = {}
    for item in ranking.get("items", []):
        chain_def = industry_chain_for_group(item.get("group"))
        key = chain_def["key"]
        bucket = chains.setdefault(
            key,
            {
                "key": key,
                "logic": chain_def["logic"],
                "groups": [],
                "leaders": [],
            },
        )
        bucket["groups"].append(item)
        bucket["leaders"].extend(item.get("leaders") or [])

    insight_items = []
    for chain in chains.values():
        groups = chain["groups"]
        if not groups:
            continue
        top_groups = sorted(groups, key=lambda item: item.get("score") or 0, reverse=True)
        avg_score = sum(item.get("score") or 0 for item in groups) / len(groups)
        avg_rps20 = sum(((item.get("groupRps") or {}).get("groupRps20") or 0) for item in groups) / len(groups)
        avg_rps50 = sum(((item.get("groupRps") or {}).get("groupRps50") or 0) for item in groups) / len(groups)
        hot_count = sum(1 for item in groups if item.get("tradeAction") in ("回调优先", "只做核心"))
        risk_count = sum(1 for item in groups if item.get("tradeAction") == "回避加仓")
        if hot_count >= 2 and avg_rps20 >= 70:
            action = "主线候选"
        elif hot_count >= 1:
            action = "局部强势"
        elif risk_count >= len(groups) * 0.6:
            action = "降温观察"
        else:
            action = "等待扩散"

        leader_seen = set()
        leaders = []
        for leader in sorted(chain["leaders"], key=lambda item: item.get("return20") or -999, reverse=True):
            code = leader.get("code")
            if not code or code in leader_seen:
                continue
            leader_seen.add(code)
            leaders.append(leader)
            if len(leaders) >= 6:
                break

        insight_items.append(
            {
                "key": chain["key"],
                "action": action,
                "logic": chain["logic"],
                "score": round(avg_score, 1),
                "rps20": round(avg_rps20, 1),
                "rps50": round(avg_rps50, 1),
                "groupCount": len(groups),
                "hotCount": hot_count,
                "riskCount": risk_count,
                "groups": [
                    {
                        "group": item.get("group"),
                        "score": item.get("score"),
                        "tradeAction": item.get("tradeAction"),
                        "stageLabel": item.get("stageLabel"),
                        "rps20": (item.get("groupRps") or {}).get("groupRps20"),
                        "rps50": (item.get("groupRps") or {}).get("groupRps50"),
                    }
                    for item in top_groups[:6]
                ],
                "leaders": leaders,
            }
        )

    insight_items.sort(
        key=lambda item: (
            item["key"] != "其他活跃题材",
            item["hotCount"],
            item["score"],
            item["rps20"],
        ),
        reverse=True,
    )
    return {
        "ok": True,
        "updatedAt": now_text(),
        "sampleSize": ranking.get("sampleSize"),
        "summary": f"{len(insight_items)} 条产业链 · 样本 {ranking.get('sampleSize') or '--'}",
        "chains": insight_items[:8],
    }


def load_sector_dataset():
    sample_rows = load_mainline_sample_rows()
    dataset = []
    for row in sample_rows:
        code = row.get("code")
        cached_klines = read_cached_ths_klines_any_age(code)
        if not code or not cached_klines:
            continue
        group = row_strength_group(row)
        if not group or group == "未匹配":
            continue
        dataset.append(
            {
                "code": code,
                "name": row.get("name") or code,
                "group": group,
                "industry": row.get("industry") or row.get("industryGroup") or group,
                "klines": cached_klines,
            }
        )
    return dataset


def stock_sector_profile(stock, rps_values):
    klines = stock["klines"]
    closes = [item.get("close") for item in klines if item.get("close") is not None]
    price = closes[-1] if closes else None
    ma20 = last_average(closes, 20) if len(closes) >= 20 else None
    ma60 = last_average(closes, 60) if len(closes) >= 60 else None
    highs = [item.get("high") or item.get("close") for item in klines[-60:] if item.get("high") or item.get("close")]
    high60 = max(highs) if highs else price
    drawdown = (high60 - price) / high60 if price and high60 else None
    ret5 = window_return(klines, 5)
    ret20 = window_return(klines, 20)
    ret50 = window_return(klines, 50)
    rps20 = percentile_rank_for_key(rps_values["return20"], stock["code"])
    rps50 = percentile_rank_for_key(rps_values["return50"], stock["code"])
    above_ma20 = bool(price and ma20 and price > ma20)
    above_ma60 = bool(price and ma60 and price > ma60)

    if ret20 is not None and ret20 >= 0.50 and rps20 is not None and rps20 >= 80:
        layer = "加速高位股"
        action = "不追，等第一次有效回踩。"
    elif rps50 is not None and rps50 >= 75 and above_ma20 and above_ma60:
        layer = "核心趋势股"
        action = "板块回调优先看它是否缩量承接。"
    elif rps50 is not None and rps50 >= 60 and above_ma60 and drawdown is not None and 0.08 <= drawdown <= 0.28:
        layer = "回调候选"
        action = "等靠近支撑并重新放量转强。"
    elif rps50 is not None and 40 <= rps50 < 70 and ret5 is not None and ret5 > 0 and ret20 is not None and ret20 < 0.25:
        layer = "后排补涨"
        action = "只看短波段，不向后排扩仓。"
    elif rps50 is not None and rps50 < 40 or (ma60 and price and price < ma60):
        layer = "弱势掉队"
        action = "反弹先按减被动或剔除观察。"
    else:
        layer = "普通观察"
        action = "等强度或买点重新确认。"

    return {
        "code": stock["code"],
        "name": stock["name"],
        "industry": stock.get("industry"),
        "layer": layer,
        "action": action,
        "price": round(price, 2) if price is not None else None,
        "return5": round(ret5 * 100, 1) if ret5 is not None else None,
        "return20": round(ret20 * 100, 1) if ret20 is not None else None,
        "return50": round(ret50 * 100, 1) if ret50 is not None else None,
        "rps20": round(rps20, 1) if rps20 is not None else None,
        "rps50": round(rps50, 1) if rps50 is not None else None,
        "drawdownPct": round(drawdown * 100, 1) if drawdown is not None else None,
        "aboveMa20": above_ma20,
        "isWatchlist": False,
    }


def build_sector_detail(group):
    target = str(group or "").strip()
    if not target:
        return {"ok": False, "reason": "缺少板块名称。"}
    dataset = load_sector_dataset()
    stocks = [item for item in dataset if item["group"] == target]
    if len(stocks) < 3:
        return {"ok": False, "reason": f"{target} 可计算样本不足。", "group": target}

    all_groups = {}
    for item in dataset:
        all_groups.setdefault(item["group"], []).append(item)
    reliable_groups = {name: items for name, items in all_groups.items() if len(items) >= 5}
    group_rps = {}
    for window in (5, 10, 20, 50):
        values = {name: group_return(items, window) for name, items in reliable_groups.items()}
        rank = percentile_rank_for_key(values, target)
        group_rps[f"groupRps{window}"] = round(rank, 1) if rank is not None else None
        value = values.get(target)
        group_rps[f"groupReturn{window}"] = round(value * 100, 1) if value is not None else None

    amount_ratio = group_amount_ratio(stocks)
    group_rps["groupAmountRatio20"] = round(amount_ratio, 2) if amount_ratio is not None else None
    above_ma20 = group_above_ma_ratio(stocks)
    positive_5 = group_positive_ratio(stocks, 5)
    red80 = sum((group_rps.get(f"groupRps{window}") or 0) >= 80 for window in (5, 10, 20, 50))
    red90 = sum((group_rps.get(f"groupRps{window}") or 0) >= 90 for window in (5, 10, 20, 50))
    state = classify_group_state(group_rps, red80, len(stocks), above_ma20, positive_5)
    quality = group_quality_view(group_rps, red80, len(stocks), above_ma20, positive_5)
    thesis = build_sector_thesis(group_rps, red80, len(stocks), above_ma20, positive_5)
    risk = build_stage_top_risk(group_rps, len(stocks), above_ma20, positive_5)

    rps_values = {
        "return20": {item["code"]: window_return(item["klines"], 20) for item in stocks},
        "return50": {item["code"]: window_return(item["klines"], 50) for item in stocks},
    }
    watch_codes = {item.get("code") for item in read_watchlist().get("items", [])}
    profiles = [stock_sector_profile(item, rps_values) for item in stocks]
    for profile in profiles:
        profile["isWatchlist"] = profile["code"] in watch_codes

    layer_order = ["核心趋势股", "回调候选", "加速高位股", "后排补涨", "普通观察", "弱势掉队"]
    layers = []
    for layer in layer_order:
        matched = [item for item in profiles if item["layer"] == layer]
        matched.sort(key=lambda item: (item.get("rps50") or -1, item.get("return20") or -999), reverse=True)
        layers.append({"key": layer, "count": len(matched), "items": matched[:10]})

    profiles.sort(key=lambda item: (item.get("isWatchlist"), item.get("rps50") or -1, item.get("return20") or -999), reverse=True)
    return {
        "ok": True,
        "updatedAt": now_text(),
        "group": target,
        "sampleSize": len(stocks),
        "groupRps": group_rps,
        "groupRed80": red80,
        "groupRed90": red90,
        "state": state,
        "quality": quality,
        "thesis": thesis,
        "risk": risk,
        "aboveMa20Ratio": round(above_ma20 * 100, 1) if above_ma20 is not None else None,
        "positive5Ratio": round(positive_5 * 100, 1) if positive_5 is not None else None,
        "amountRatio20": round(amount_ratio, 2) if amount_ratio is not None else None,
        "layers": layers,
        "watchlistItems": [item for item in profiles if item["isWatchlist"]],
        "topItems": profiles[:20],
    }


def format_strength_value(value):
    return "待接入" if value is None else f"{value:.1f}"


def build_support_view(
    price,
    ma20,
    ma60,
    low_10,
    low_20,
    atr=None,
    prior_low_10=None,
    prior_low_20=None,
):
    effective_atr = max(atr or price * 0.025, price * 0.008)
    prior_10 = prior_low_10 if prior_low_10 is not None else low_10
    prior_20 = prior_low_20 if prior_low_20 is not None else low_20
    cluster_tolerance = max(effective_atr * 0.45, price * 0.008)
    reclaim_allowance = max(effective_atr * 0.35, price * 0.008)

    candidates = []
    if prior_10 and prior_20 and abs(prior_10 - prior_20) <= cluster_tolerance:
        candidates.append(("10/20日先前平台", (prior_10 + prior_20) / 2, 3.2))
    else:
        candidates.extend(
            [
                ("10日先前低点", prior_10, 2.1),
                ("20日先前平台", prior_20, 2.6),
            ]
        )
    candidates.extend([("MA20", ma20, 2.3), ("MA60", ma60, 2.5)])
    supports = [
        (label, value, weight)
        for label, value, weight in candidates
        if value and 0 < value <= price + reclaim_allowance
    ]
    if not supports:
        return {
            "available": False,
            "label": "有效支撑待形成",
            "reason": "当前价格已明显跌破先前平台和主要均线，不能用当日新低制造支撑。",
            "price": None,
            "atr14": round(effective_atr, 2),
            "trialLow": None,
            "trialHigh": None,
            "panicTriggerPrice": None,
            "reclaimConfirmPrice": None,
            "secondConfirmPrice": None,
            "repairPrice": round(min(value for value in (ma20, ma60) if value), 2) if any((ma20, ma60)) else None,
            "repairState": "等待重新站回中期趋势线",
            "invalidPrice": None,
            "confluence": [],
            "secondarySupportLabel": None,
            "secondarySupportPrice": None,
        }

    label, support, _ = max(supports, key=lambda item: item[1])
    confluence = [
        other_label
        for other_label, other_value, _ in supports
        if abs(other_value - support) <= cluster_tolerance
    ]
    deeper_supports = sorted(
        [
            (other_label, other_value)
            for other_label, other_value, _ in supports
            if other_value < support - cluster_tolerance
        ],
        key=lambda item: item[1],
        reverse=True,
    )
    secondary_label, secondary_price = deeper_supports[0] if deeper_supports else (None, None)
    display_label = " + ".join(dict.fromkeys(confluence)) or label
    invalid_gap = max(effective_atr * 0.65, support * 0.012)
    invalid = round(support - invalid_gap, 2)
    trial_low = round(max(invalid + effective_atr * 0.2, support - effective_atr * 0.15), 2)
    trial_high = round(support + max(effective_atr * 0.35, support * 0.008), 2)
    panic_trigger = round(support + effective_atr * 0.05, 2)
    reclaim_price = round(support + effective_atr * 0.25, 2)
    second_confirm = round(min(support * 1.045, support + effective_atr * 0.5), 2)

    overhead = [
        value
        for value in (ma20, ma60)
        if value and value > price + effective_atr * 0.2
    ]
    repair_price = round(min(overhead), 2) if overhead else None
    return {
        "available": True,
        "label": display_label,
        "reason": f"支撑来自{'、'.join(confluence)}，并已排除当日K线自我定义。",
        "price": round(support, 2),
        "atr14": round(effective_atr, 2),
        "trialLow": trial_low,
        "trialHigh": trial_high,
        "panicTriggerPrice": panic_trigger,
        "reclaimConfirmPrice": reclaim_price,
        "secondConfirmPrice": second_confirm,
        "repairPrice": repair_price,
        "repairState": "等待修复" if repair_price is not None else "中期趋势线已在价格下方",
        "invalidPrice": invalid,
        "confluence": confluence,
        "secondarySupportLabel": secondary_label,
        "secondarySupportPrice": round(secondary_price, 2) if secondary_price is not None else None,
    }


def build_execution_plan(
    price,
    support_view,
    add_price,
    timing_score,
    strength_view,
    market_sentiment,
    latest_bar,
    ma20,
    previous_bar=None,
    today_volume_ratio_20=None,
    data_stale=False,
):
    if not support_view.get("available"):
        reason = support_view.get("reason") or "有效支撑尚未形成。"
        return {
            "trialLow": None,
            "trialHigh": None,
            "trialStatus": "无有效支撑",
            "liquidityStage": "等待支撑形成",
            "trialDistancePct": None,
            "executionGate": "禁止买入",
            "blockReasons": [reason],
            "blockActions": ["等待先前平台或主要均线重新形成有效承接"],
            "trialPosition": "0%",
            "supportLabel": support_view.get("label"),
            "supportPrice": None,
            "supportAtr": support_view.get("atr14"),
            "secondarySupportLabel": support_view.get("secondarySupportLabel"),
            "secondarySupportPrice": support_view.get("secondarySupportPrice"),
            "panicTriggerPrice": None,
            "reclaimConfirmPrice": None,
            "panicTouched": False,
            "panicReleased": False,
            "sellingExhausted": False,
            "sameDayReclaim": False,
            "nextDayConfirmed": False,
            "reclaimConfirmed": False,
            "confirmationExpired": False,
            "repairConfirmPrice": support_view.get("repairPrice"),
            "repairState": support_view.get("repairState"),
            "addConfirmPrice": None,
            "addPosition": "暂不加仓",
            "invalidPrice": None,
            "timingScore": timing_score,
            "signals": [
                f"执行闸门：禁止买入；{reason}",
                "当日新低不能自动成为支撑，必须等待先前结构重新确认。",
            ],
        }

    trial_low = support_view["trialLow"]
    trial_high = support_view["trialHigh"]
    invalid = support_view["invalidPrice"]
    repair_price = support_view["repairPrice"]
    panic_trigger = support_view["panicTriggerPrice"]
    reclaim_price = support_view["reclaimConfirmPrice"]
    atr = support_view.get("atr14") or max(price * 0.025, 0.01)
    bar_low = latest_bar.get("low") or price
    bar_high = latest_bar.get("high") or price
    bar_open = latest_bar.get("open") or price
    bar_range = max(0, bar_high - bar_low)
    lower_shadow = max(0, min(bar_open, price) - bar_low)
    intraday_rebound = max(0, price - bar_low)
    close_position = intraday_rebound / bar_range if bar_range else 0.5
    pct_change = latest_bar.get("pctChange")
    panic_touched = bar_low <= panic_trigger
    panic_event = panic_touched and (
        (pct_change is not None and pct_change <= -1.5)
        or bar_range >= atr * 0.9
        or (today_volume_ratio_20 is not None and today_volume_ratio_20 >= 1.15)
    )
    selling_exhausted = (
        panic_event
        and lower_shadow >= atr * 0.2
        and intraday_rebound >= atr * 0.3
        and close_position >= 0.55
    )
    same_day_reclaim = selling_exhausted and price >= reclaim_price

    previous_bar = previous_bar or {}
    previous_low = previous_bar.get("low")
    previous_high = previous_bar.get("high")
    previous_open = previous_bar.get("open")
    previous_close = previous_bar.get("close")
    previous_range = (
        max(0, previous_high - previous_low)
        if previous_high is not None and previous_low is not None
        else 0
    )
    previous_rebound = (
        max(0, previous_close - previous_low)
        if previous_close is not None and previous_low is not None
        else 0
    )
    previous_close_position = previous_rebound / previous_range if previous_range else 0
    previous_exhausted = bool(
        previous_low is not None
        and previous_low <= panic_trigger
        and previous_open is not None
        and previous_close is not None
        and max(0, min(previous_open, previous_close) - previous_low) >= atr * 0.2
        and previous_rebound >= atr * 0.3
        and previous_close_position >= 0.55
    )
    next_day_confirmed = bool(
        previous_exhausted
        and bar_low >= previous_low - atr * 0.15
        and price >= reclaim_price
        and price >= previous_close
        and close_position >= 0.45
    )
    reclaim_confirmed = same_day_reclaim or next_day_confirmed
    confirmation_expired = bool(
        reclaim_confirmed
        and add_price is not None
        and price > add_price + atr * 0.35
    )
    panic_released = selling_exhausted

    if price < invalid:
        trial_status = "结构失效"
        liquidity_stage = "失效"
        trial_distance_pct = round((invalid - price) / price * 100, 1) if price else None
    elif confirmation_expired:
        trial_status = "确认已过等待回踩"
        liquidity_stage = "确认后偏离"
        trial_distance_pct = round((price - add_price) / price * 100, 1) if price and add_price else None
    elif next_day_confirmed:
        trial_status = "次日确认"
        liquidity_stage = "低点确认"
        trial_distance_pct = 0
    elif same_day_reclaim:
        trial_status = "日内回收"
        liquidity_stage = "回收待次日确认"
        trial_distance_pct = 0
    elif selling_exhausted:
        trial_status = "抛压衰竭待回收"
        liquidity_stage = "抛压衰竭"
        trial_distance_pct = 0
    elif panic_event:
        trial_status = "恐慌发生未衰竭"
        liquidity_stage = "恐慌未完成"
        trial_distance_pct = 0
    elif trial_low <= price <= trial_high:
        trial_status = "低吸区内待触发"
        liquidity_stage = "低位等待"
        trial_distance_pct = 0
    elif price < trial_low:
        trial_status = "低于低吸区待修复"
        liquidity_stage = "弱势下探"
        trial_distance_pct = round((trial_low - price) / price * 100, 1)
    else:
        trial_status = "高于低吸区"
        liquidity_stage = "区间中高位"
        trial_distance_pct = round((price - trial_high) / price * 100, 1)

    priority = (strength_view or {}).get("priority") or {}
    priority_level = priority.get("level")
    group_gate = ((strength_view or {}).get("groupState") or {}).get("gate")
    group_state = (strength_view or {}).get("groupState") or {}
    group_rps = (strength_view or {}).get("groupRps") or {}
    stage_top = (strength_view or {}).get("stageTopRisk") or {}
    state = ((market_sentiment or {}).get("marketState") or {}).get("state")

    destructive_bar = pct_change is not None and pct_change <= -5
    weak_close = pct_change is not None and pct_change <= -3 and price <= (ma20 or price)
    block_reasons = []
    block_actions = []
    if data_stale:
        latest_date = parse_kline_date(latest_bar.get("date"))
        previous_date = parse_kline_date(previous_bar.get("date"))
        expected_date = latest_expected_kline_date()
        latest_text = latest_date.isoformat() if latest_date else str(latest_bar.get("date") or "未知")
        expected_text = expected_date.isoformat() if expected_date else "最近完整交易日"
        if (
            latest_bar.get("temporary")
            and latest_date
            and previous_date
            and (latest_date - previous_date).days > 7
        ):
            block_reasons.append(
                f"最新价已到{latest_text}，但完整日K停在{previous_date.isoformat()}，中间缺口未补齐"
            )
            block_actions.append("手动刷新该股票，等待完整日K补齐后重新计算")
        else:
            block_reasons.append(f"行情仅到{latest_text}，应更新至{expected_text}")
            block_actions.append("手动刷新该股票，等待行情源补齐后重新计算")
    if stage_top.get("level") == "high":
        block_reasons.append("板块命中阶段顶部风险")
        block_actions.append("等待顶部风险降至高位分歧以下")
    if group_gate == "禁止加权":
        rps20 = group_rps.get("groupRps20")
        above_ratio = group_state.get("aboveMa20Ratio")
        details = []
        if rps20 is not None:
            details.append(f"RPS20为{rps20:.1f}")
        if above_ratio is not None:
            details.append(f"MA20上方占比{above_ratio:.1f}%")
        detail_text = f"（{'，'.join(details)}）" if details else ""
        block_reasons.append(
            f"板块{group_state.get('trend') or '退潮'}/{group_state.get('heat') or '降温'}{detail_text}"
        )
        block_actions.append("等待板块RPS20回到60以上且MA20上方占比恢复到55%以上")
    if destructive_bar:
        block_reasons.append(f"当日跌幅{pct_change:.2f}%，属于破坏性长阴")
        block_actions.append("等待止跌并站回趋势修复位")
    elif weak_close:
        block_reasons.append(f"当日下跌{abs(pct_change):.2f}%且收盘未守住MA20")
        block_actions.append("等待重新站回MA20并回踩确认")

    if block_reasons:
        execution_gate = "禁止买入"
        trial_position = "0%"
        add_position = "暂不加仓"
    elif trial_status in ("结构失效", "低于低吸区待修复"):
        execution_gate = "等待修复"
        trial_position = "0%"
        add_position = "等待重新站回结构支撑"
    elif trial_status in ("高于低吸区", "确认已过等待回踩"):
        execution_gate = "等待低吸位"
        trial_position = "0%"
        add_position = (
            "等待回踩进入计划区，原确认价不再有效"
            if trial_status == "确认已过等待回踩"
            else "等待进入计划低吸区"
        )
    elif trial_status == "次日确认" and priority_level in ("A", "A-") and timing_score >= 32:
        execution_gate = "允许轻仓试错"
        trial_position = "0%-5%"
        add_position = "二次回踩不破后再加3%-5%"
    elif trial_status == "次日确认" and priority_level in ("B+", "B") and timing_score >= 28:
        execution_gate = "谨慎试错"
        trial_position = "0%-3%"
        add_position = "确认后不超5%"
    elif trial_status == "日内回收" and priority_level in ("A", "A-") and timing_score >= 30:
        execution_gate = "允许极小仓低吸"
        trial_position = "0%-2%"
        add_position = "次日不创新低后再评估"
    elif trial_status == "次日确认" and timing_score >= 28:
        execution_gate = "谨慎试错"
        trial_position = "0%-3%"
        add_position = "等板块质量与承接确认"
    elif trial_status == "抛压衰竭待回收" and priority_level in ("A", "A-") and timing_score >= 34:
        execution_gate = "允许极小仓低吸"
        trial_position = "0%-1%"
        add_position = "只博弈最低点，未回收不加仓"
    elif trial_status in ("日内回收", "抛压衰竭待回收"):
        execution_gate = "等待回收"
        trial_position = "0%"
        add_position = "等待次日不创新低"
    elif trial_status == "恐慌发生未衰竭":
        execution_gate = "等待衰竭"
        trial_position = "0%"
        add_position = "放量下跌不等于抛压结束"
    elif trial_status == "低吸区内待触发":
        execution_gate = "等待恐慌触发"
        trial_position = "0%"
        add_position = "没有释放和回收不提前埋伏"
    else:
        execution_gate = "观察"
        trial_position = "0%"
        add_position = "暂不加仓"

    if state in ("冰点", "深冰点") and priority_level in ("A", "A-", "B+"):
        trial_note = "情绪冰点可提高试错主动性，但仍只对强方向/强个股有效。"
    elif state == "过热":
        trial_note = "市场过热时降低新开仓，避免用情绪高点追确认价。"
    else:
        trial_note = "按个股结构执行，情绪不额外放大仓位。"

    return {
        "trialLow": trial_low,
        "trialHigh": trial_high,
        "trialStatus": trial_status,
        "liquidityStage": liquidity_stage,
        "trialDistancePct": trial_distance_pct,
        "executionGate": execution_gate,
        "blockReasons": block_reasons,
        "blockActions": block_actions,
        "trialPosition": trial_position,
        "supportLabel": support_view["label"],
        "supportPrice": support_view["price"],
        "supportAtr": atr,
        "secondarySupportLabel": support_view.get("secondarySupportLabel"),
        "secondarySupportPrice": support_view.get("secondarySupportPrice"),
        "panicTriggerPrice": panic_trigger,
        "reclaimConfirmPrice": reclaim_price,
        "panicTouched": panic_touched,
        "panicReleased": panic_released,
        "sellingExhausted": selling_exhausted,
        "sameDayReclaim": same_day_reclaim,
        "nextDayConfirmed": next_day_confirmed,
        "reclaimConfirmed": reclaim_confirmed,
        "confirmationExpired": confirmation_expired,
        "repairConfirmPrice": repair_price,
        "repairState": support_view.get("repairState"),
        "addConfirmPrice": add_price,
        "addPosition": add_position,
        "invalidPrice": invalid,
        "timingScore": timing_score,
        "signals": [
            (
                f"执行闸门：{execution_gate}；{'；'.join(block_reasons)}。"
                + (f" 解除条件：{'；'.join(block_actions)}。" if block_actions else "")
                if block_reasons
                else f"执行闸门：{execution_gate}。"
            ),
            f"{support_view['label']}约 {support_view['price']:.2f}，ATR14约 {atr:.2f}，计划低吸区 {trial_low:.2f}-{trial_high:.2f}，当前{trial_status}。",
            (
                f"第二防线为{support_view.get('secondarySupportLabel')}约 {support_view.get('secondarySupportPrice'):.2f}，第一支撑失效后只观察，不直接向下摊仓。"
                if support_view.get("secondarySupportPrice") is not None
                else "当前没有可靠的第二防线，第一支撑失效后必须退出试错。"
            ),
            f"恐慌触发价 {panic_trigger:.2f}；触及只代表恐慌发生，下影回收和收盘位置才判断抛压是否衰竭。",
            f"回收确认价 {reclaim_price:.2f}；日内回收后仍要看次日是否不创新低。",
            (
                f"中期趋势修复位 {repair_price:.2f}，它用于判断反弹是否升级为趋势，不是买点。"
                if repair_price is not None
                else "当前价格已在主要中期趋势线上方，不再虚构额外的趋势修复价。"
            ),
            f"二次确认价 {add_price:.2f}，仅在低点确认后有效；价格明显越过后必须等待回踩，不能追着旧确认价加仓。",
            f"失效位 {invalid:.2f}，已按ATR留出正常波动空间，跌破后处理试错仓。",
            trial_note,
        ],
    }


def build_decision_loop(fundamental_view, strength_view, timeframe_view, execution_plan, market_sentiment):
    strength_available = strength_view.get("available")
    sector = strength_view.get("sectorThesis") or {}
    priority = strength_view.get("priority") or {}
    group = strength_view.get("group") or "主线待确认"
    mainline = (
        f"{group} · {sector.get('phase', '阶段待确认')} · {sector.get('action', priority.get('label', '观察'))}"
        if strength_available
        else "主线待确认 · 不因个股上涨放大仓位"
    )

    posture = timeframe_view.get("posture") or "等待确认"
    verdict = timeframe_view.get("verdict") or "三周期待确认"
    trial_status = execution_plan.get("trialStatus") or "待确认"
    gate = execution_plan.get("executionGate") or "观察"
    invalid = execution_plan.get("invalidPrice")
    market_state = ((market_sentiment or {}).get("marketState") or {}).get("state") or "市场待确认"

    if gate in ("禁止买入", "等待修复"):
        passive = "反弹先降被动，不把修复当反转。"
    elif trial_status == "高于低吸区":
        passive = "强也不追，等量化回撤进入计划低吸区。"
    elif trial_status == "次日确认":
        passive = "低位已经过次日确认，只按计划小仓执行，错了按失效位处理。"
    elif trial_status == "日内回收":
        passive = "日内回收尚未经过次日确认，不提前扩大仓位。"
    elif trial_status == "抛压衰竭待回收":
        passive = "仅强主线允许极小仓博弈，未回收前不增加仓位。"
    elif trial_status == "确认已过等待回踩":
        passive = "原确认价已经过期，等待二次回踩，不在偏离后追仓。"
    elif trial_status == "低吸区内待触发":
        passive = "位置够低但尚未释放，不在区间中部提前埋伏。"
    elif trial_status in ("低于低吸区待修复", "结构失效"):
        passive = "先等重新站回先前支撑，避免在下跌结构里向下摊仓。"
    else:
        passive = "先保持观察，等价格和量能给确认。"

    if fundamental_view.get("available"):
        fundamental = f"{fundamental_view.get('stage')} · {fundamental_view.get('score')}/30"
    else:
        fundamental = "基本面待夯实 · 不给中长期确定性加分"

    return {
        "mainline": mainline,
        "cycle": f"{posture} · {verdict}",
        "action": f"{gate} · {trial_status}",
        "passive": passive,
        "risk": f"失效位 {invalid:.2f} · 市场{market_state}" if isinstance(invalid, (int, float)) else f"失效待确认 · 市场{market_state}",
        "fundamental": fundamental,
        "signals": [
            f"主线：{mainline}",
            f"周期：{posture}；{verdict}",
            f"动作：{gate}，当前位置{trial_status}。",
            f"被动处理：{passive}",
            f"风控：{('失效位 %.2f' % invalid) if isinstance(invalid, (int, float)) else '失效位待确认'}。",
            f"基本面：{fundamental}",
        ],
    }


def checklist_item(key, label, status, evidence, action):
    return {
        "key": key,
        "label": label,
        "status": status,
        "evidence": evidence,
        "action": action,
    }


def build_trader_checklist(
    total,
    fundamental_view,
    strength_view,
    timeframe_view,
    execution_plan,
    latest_bar,
    metrics,
):
    group_state = strength_view.get("groupState") or {}
    sector = strength_view.get("sectorThesis") or {}
    priority = strength_view.get("priority") or {}
    group = strength_view.get("group") or "主线待确认"
    gate = execution_plan.get("executionGate") or "观察"
    trial_status = execution_plan.get("trialStatus") or "待确认"
    time_daily = timeframe_view.get("daily") or {}
    time_weekly = timeframe_view.get("weekly") or {}
    time_monthly = timeframe_view.get("monthly") or {}
    amount_ratio = metrics.get("todayVolumeRatio20") or metrics.get("volumeRatio5To20")

    mainline_ok = strength_view.get("available") and group_state.get("gate") != "禁止加权"
    cycle_ok = (
        time_monthly.get("action") != "降低仓位"
        and time_weekly.get("action") != "降低仓位"
        and gate not in ("禁止买入", "等待修复")
    )
    entry_ok = trial_status in ("次日确认", "日内回收", "抛压衰竭待回收") and gate in (
        "允许轻仓试错",
        "谨慎试错",
        "允许极小仓低吸",
    )
    volume_ok = amount_ratio is not None and 0.75 <= amount_ratio <= 1.8
    risk_ok = gate != "禁止买入" and bool(execution_plan.get("invalidPrice"))
    fundamental_quality = (fundamental_view.get("quality") or {}).get("level")
    fundamental_ok = fundamental_view.get("available") and fundamental_quality not in ("待夯实", None)
    pressure_ok = gate not in ("等待低吸位", "等待恐慌触发", "等待衰竭", "等待回收")

    def level_text(value):
        return f"{value:.2f}" if isinstance(value, (int, float)) else "待形成"

    items = [
        checklist_item(
            "mainline",
            "是否在主线内",
            "pass" if mainline_ok else "fail",
            f"{group} · {sector.get('phase', '阶段待确认')} · {priority.get('level', '未入级')}",
            "不在主线或板块退潮时，只能观察或做减被动。",
        ),
        checklist_item(
            "cycle",
            "月周日是否同向",
            "pass" if cycle_ok else "warn",
            f"月线{time_monthly.get('phase', '待确认')}，周线{time_weekly.get('phase', '待确认')}，日线{time_daily.get('phase', '待确认')}",
            "大周期不支持时，日线反弹不当成中线反转。",
        ),
        checklist_item(
            "entry",
            "是否形成流动性低点",
            "pass" if entry_ok else "warn",
            f"{gate} · {trial_status}",
            "必须区分恐慌发生、抛压衰竭、日内回收和次日确认，区间中部不操作。",
        ),
        checklist_item(
            "volume",
            "反弹/回踩量能是否健康",
            "pass" if volume_ok else "warn",
            f"量能比 {amount_ratio:.2f}x" if amount_ratio is not None else "量能待确认",
            "缩量承接优于放量乱冲；放量突破后要看次日承接。",
        ),
        checklist_item(
            "pressure",
            "到压力位是否有承接",
            "pass" if pressure_ok else "warn",
            f"趋势修复位 {level_text(execution_plan.get('repairConfirmPrice'))}，二次确认价 {level_text(execution_plan.get('addConfirmPrice'))}",
            "到修复位和确认价附近没有承接，优先降低被动。",
        ),
        checklist_item(
            "risk",
            "失效位是否明确",
            "pass" if risk_ok else "fail",
            f"失效位 {level_text(execution_plan.get('invalidPrice'))}；试错仓 {execution_plan.get('trialPosition') or '0%'}",
            "先定错了怎么办，再谈买入。",
        ),
        checklist_item(
            "fundamental",
            "基本面是否夯实",
            "pass" if fundamental_ok else "warn",
            f"{fundamental_view.get('stage', '待接入')} · {fundamental_view.get('score', '--')}/30 · {fundamental_quality or '待夯实'}",
            "基本面不夯实，只做行情波段，不给长线信仰加分。",
        ),
    ]

    pass_count = sum(1 for item in items if item["status"] == "pass")
    fail_count = sum(1 for item in items if item["status"] == "fail")
    if fail_count:
        verdict = "否决项未过"
        action = "不主动买入，若有仓位用反弹降被动。"
    elif entry_ok and pass_count >= 5 and total >= 65:
        verdict = "允许小仓试错"
        action = "按试错仓位执行，跌破失效位先处理。"
    elif gate in ("等待低吸位", "等待恐慌触发", "等待衰竭", "等待回收"):
        verdict = "等待流动性买点"
        action = "放进计划，不追当前价，也不在区间中部提前埋伏。"
    else:
        verdict = "继续观察"
        action = "等主线、周期、买点至少再补一项确认。"

    return {
        "verdict": verdict,
        "action": action,
        "passCount": pass_count,
        "warnCount": sum(1 for item in items if item["status"] == "warn"),
        "failCount": fail_count,
        "items": items,
    }


def eastmoney_quote_time(value):
    try:
        timestamp = int(value)
    except (TypeError, ValueError):
        return None, None
    moment = datetime.fromtimestamp(timestamp)
    return moment.strftime("%Y-%m-%d"), moment.strftime("%H:%M:%S")


def prefetch_eastmoney_quotes(codes):
    normalized_codes = [normalize_security_code(code) for code in codes]
    normalized_codes = [code for code in normalized_codes if code]
    if not normalized_codes or not ENABLE_EASTMONEY:
        return {"ok": False, "count": 0, "reason": "没有可批量刷新的证券代码。"}
    if not wait_for_provider_slot(max_wait_seconds=30):
        return {"ok": False, "count": 0, "reason": "东财批量报价等待超时。"}

    secids = ",".join(eastmoney_secid(code) for code in normalized_codes)
    fields = ",".join(
        ["f2", "f3", "f4", "f5", "f6", "f8", "f12", "f14", "f15", "f16", "f17", "f18", "f124"]
    )
    url = (
        "https://push2.eastmoney.com/api/qt/ulist.np/get"
        f"?secids={secids}&fields={fields}"
    )
    result = eastmoney_request_json(url)
    if not result.get("ok"):
        return {"ok": False, "count": 0, "reason": result.get("reason")}

    rows = ((result.get("data") or {}).get("data") or {}).get("diff") or []
    cached_count = 0
    for row in rows:
        code = normalize_security_code(row.get("f12"))
        if not code:
            continue
        quote_date, quote_clock = eastmoney_quote_time(row.get("f124"))
        quote = {
            "source": "eastmoney",
            "fetchedAt": int(time.time()),
            "code": code,
            "name": row.get("f14"),
            "price": eastmoney_price(row.get("f2"), code),
            "high": eastmoney_price(row.get("f15"), code),
            "low": eastmoney_price(row.get("f16"), code),
            "open": eastmoney_price(row.get("f17"), code),
            "prevClose": eastmoney_price(row.get("f18"), code),
            "previousClose": eastmoney_price(row.get("f18"), code),
            "change": eastmoney_price(row.get("f4"), code),
            "pctChange": scaled(row.get("f3")),
            "turnoverRate": scaled(row.get("f8")),
            "volume": row.get("f5"),
            "amount": row.get("f6"),
            "quoteTime": quote_date,
            "quoteClock": quote_clock,
            "isIntraday": bool(
                quote_date == datetime.now().strftime("%Y-%m-%d")
                and 915 <= int(datetime.now().strftime("%H%M")) <= 1510
            ),
        }
        if quote["price"] is not None:
            write_quote_cache(code, quote)
            cached_count += 1
    return {
        "ok": cached_count > 0,
        "count": cached_count,
        "requested": len(normalized_codes),
        "reason": None if cached_count else "东财批量报价未返回有效证券。",
    }


def prefetch_tencent_quotes(codes):
    normalized_codes = [normalize_security_code(code) for code in codes]
    normalized_codes = [code for code in normalized_codes if code]
    if not normalized_codes or not ENABLE_TENCENT:
        return {"ok": False, "count": 0, "reason": "腾讯批量行情未启用。"}

    symbols = [
        ("sh" if code.startswith(("5", "6")) else "sz") + code
        for code in normalized_codes
    ]
    request = urllib.request.Request(
        "https://qt.gtimg.cn/q=" + ",".join(symbols),
        headers={
            "User-Agent": "Mozilla/5.0 AShareScorer/0.1",
            "Referer": "https://gu.qq.com/",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            text = response.read().decode("gb18030", errors="ignore")
    except (
        urllib.error.URLError,
        TimeoutError,
        http.client.RemoteDisconnected,
        http.client.IncompleteRead,
        OSError,
    ) as error:
        return {"ok": False, "count": 0, "reason": f"腾讯批量行情失败：{error}"}

    cached_count = 0
    for match in re.finditer(r'v_[^=]+="([^"]*)"', text):
        fields = match.group(1).split("~")
        if len(fields) < 39:
            continue
        code = normalize_security_code(fields[2])
        price = bridge_float(fields[3])
        timestamp = fields[30]
        quote_date = (
            f"{timestamp[:4]}-{timestamp[4:6]}-{timestamp[6:8]}"
            if len(timestamp) >= 8
            else None
        )
        quote_clock = (
            f"{timestamp[8:10]}:{timestamp[10:12]}:{timestamp[12:14]}"
            if len(timestamp) >= 14
            else None
        )
        transaction = fields[35].split("/") if len(fields) > 35 else []
        amount = bridge_float(transaction[2]) if len(transaction) >= 3 else None
        quote = {
            "source": "tencent",
            "fetchedAt": int(time.time()),
            "code": code,
            "name": fields[1],
            "price": price,
            "open": bridge_float(fields[5]),
            "high": bridge_float(fields[33]),
            "low": bridge_float(fields[34]),
            "prevClose": bridge_float(fields[4]),
            "previousClose": bridge_float(fields[4]),
            "change": bridge_float(fields[31]),
            "pctChange": bridge_float(fields[32]),
            "turnoverRate": bridge_float(fields[38]),
            "volume": bridge_float(fields[6]),
            "amount": amount,
            "quoteTime": quote_date,
            "quoteClock": quote_clock,
            "isIntraday": bool(
                quote_date == datetime.now().strftime("%Y-%m-%d")
                and 915 <= int(datetime.now().strftime("%H%M")) <= 1510
            ),
        }
        if code and price is not None:
            write_quote_cache(code, quote)
            cached_count += 1
    return {
        "ok": cached_count > 0,
        "count": cached_count,
        "requested": len(normalized_codes),
        "reason": None if cached_count else "腾讯批量行情未返回有效证券。",
    }


def prefetch_cloud_quotes(codes):
    normalized_codes = list(codes)
    eastmoney = prefetch_eastmoney_quotes(normalized_codes)
    if eastmoney.get("ok") and eastmoney.get("count") == len(normalized_codes):
        eastmoney["provider"] = "eastmoney"
        return eastmoney
    tencent = prefetch_tencent_quotes(normalized_codes)
    if tencent.get("ok") and tencent.get("count") == len(normalized_codes):
        tencent["provider"] = "tencent"
        tencent["fallbackReason"] = eastmoney.get("reason")
        return tencent
    return {
        "ok": False,
        "count": max(eastmoney.get("count", 0), tencent.get("count", 0)),
        "requested": len(normalized_codes),
        "reason": (
            f"东财：{eastmoney.get('reason') or '返回不完整'}；"
            f"腾讯：{tencent.get('reason') or '返回不完整'}"
        ),
    }


def fetch_eastmoney_quote(code, force_refresh=False, wait_for_slot=False):
    if not ENABLE_EASTMONEY:
        return {
            "ok": False,
            "reason": "东财 provider 默认关闭，当前主数据源为同花顺。",
        }

    cached = read_quote_cache(code)
    if cached and not force_refresh:
        return {"ok": True, "quote": cached, "fromCache": True}
    if wait_for_slot and not wait_for_provider_slot():
        return {"ok": False, "reason": "东财实时价刷新等待超时，外部请求仍在冷却。"}

    fields = ",".join(
        ["f43", "f44", "f45", "f46", "f47", "f48", "f57", "f58", "f60", "f86", "f168", "f169", "f170"]
    )
    url = "https://push2.eastmoney.com/api/qt/stock/get" f"?secid={eastmoney_secid(code)}&fields={fields}"
    result = eastmoney_request_json(url)
    if not result.get("ok"):
        return result

    data = (result.get("data") or {}).get("data") or {}
    if not data:
        return {"ok": False, "reason": "东财行情返回为空。"}

    quote_date, quote_clock = eastmoney_quote_time(data.get("f86"))
    quote = {
        "source": "eastmoney",
        "fetchedAt": int(time.time()),
        "code": data.get("f57") or code,
        "name": data.get("f58"),
        "price": eastmoney_price(data.get("f43"), code),
        "high": eastmoney_price(data.get("f44"), code),
        "low": eastmoney_price(data.get("f45"), code),
        "open": eastmoney_price(data.get("f46"), code),
        "prevClose": eastmoney_price(data.get("f60"), code),
        "previousClose": eastmoney_price(data.get("f60"), code),
        "change": eastmoney_price(data.get("f169"), code),
        "pctChange": scaled(data.get("f170")),
        "turnoverRate": scaled(data.get("f168")),
        "volume": data.get("f47"),
        "amount": data.get("f48"),
        "quoteTime": quote_date,
        "quoteClock": quote_clock,
        "isIntraday": bool(
            quote_date == datetime.now().strftime("%Y-%m-%d")
            and 915 <= int(datetime.now().strftime("%H%M")) <= 1510
        ),
    }
    write_quote_cache(code, quote)
    return {"ok": True, "quote": quote, "fromCache": False}


def as_float(value):
    if value in (None, "", "-"):
        return None
    return float(value)


def plausible_turnover(value):
    number = as_float(value)
    if number is None:
        return None
    # 同花顺不同端返回字段不完全一致；换手率通常是 0-100 的百分数。
    return number if 0 < number <= 100 else None


def fetch_eastmoney_klines(code, limit=160, force=False, cache_prefix=""):
    cache_key = f"{cache_prefix}{code}"
    cached = read_kline_cache(cache_key)
    if cached and not force:
        return {"ok": True, "klines": cached, "fromCache": True}

    fields1 = "f1,f2,f3,f4,f5,f6"
    fields2 = "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"
    url = (
        "https://push2his.eastmoney.com/api/qt/stock/kline/get"
        f"?secid={eastmoney_secid(code)}&ut=fa5fd1943c7b386f172d6893dbfba10b"
        f"&klt=101&fqt=1&beg=0&end=20500101&lmt={limit}"
        f"&fields1={fields1}&fields2={fields2}"
    )
    result = eastmoney_request_json(url, force=force)
    if not result.get("ok"):
        return result

    raw_klines = ((result.get("data") or {}).get("data") or {}).get("klines") or []
    klines = []
    for row in raw_klines:
        cols = row.split(",")
        if len(cols) < 11:
            continue
        klines.append(
            {
                "date": cols[0],
                "open": as_float(cols[1]),
                "close": as_float(cols[2]),
                "high": as_float(cols[3]),
                "low": as_float(cols[4]),
                "volume": as_float(cols[5]),
                "amount": as_float(cols[6]),
                "amplitude": as_float(cols[7]),
                "pctChange": as_float(cols[8]),
                "change": as_float(cols[9]),
                "turnoverRate": as_float(cols[10]),
            }
        )
    if len(klines) < 60:
        return {"ok": False, "reason": "日K数据不足，暂无法评分。"}
    write_kline_cache(cache_key, klines)
    return {"ok": True, "klines": klines, "fromCache": False, "provider": "eastmoney"}


def parse_ths_kline_payload(text):
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return []
    payload = json.loads(text[start : end + 1])
    raw_data = payload.get("data") or payload.get("flashData") or ""
    if isinstance(raw_data, dict):
        raw_data = raw_data.get("data") or raw_data.get("klines") or ""
    if isinstance(raw_data, list):
        records = raw_data
    else:
        records = [item for item in str(raw_data).replace("|", ";").split(";") if item]

    klines = []
    for row in records:
        cols = row if isinstance(row, list) else str(row).split(",")
        if len(cols) < 6:
            continue
        # 常见同花顺日K字段：date,open,high,low,close,volume,amount...
        date = str(cols[0])
        open_price = as_float(cols[1])
        high = as_float(cols[2])
        low = as_float(cols[3])
        close = as_float(cols[4])
        volume = as_float(cols[5])
        amount = as_float(cols[6]) if len(cols) > 6 else None
        turnover_rate = next(
            (
                value
                for value in (
                    plausible_turnover(cols[index])
                    for index in (10, 9, 8, 7)
                    if len(cols) > index
                )
                if value is not None
            ),
            None,
        )
        prev_close = klines[-1]["close"] if klines else None
        pct_change = round((close - prev_close) / prev_close * 100, 2) if close and prev_close else None
        klines.append(
            {
                "date": date,
                "open": open_price,
                "close": close,
                "high": high,
                "low": low,
                "volume": volume,
                "amount": amount,
                "amplitude": None,
                "pctChange": pct_change,
                "change": round(close - prev_close, 2) if close and prev_close else None,
                "turnoverRate": turnover_rate,
            }
        )
    return [item for item in klines if item["close"] is not None]


def parse_ths_intraday_quote(text, code):
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    payload = json.loads(text[start : end + 1])
    data = payload.get(f"hs_{code}") or {}
    records = [item for item in str(data.get("data") or "").split(";") if item]
    points = []
    for record in records:
        cols = record.split(",")
        if len(cols) < 2:
            continue
        price = as_float(cols[1])
        if price is not None:
            points.append((cols[0], price))
    if not points:
        return None
    previous_close = as_float(data.get("pre"))
    latest_time, price = points[-1]
    point_prices = [item[1] for item in points]
    pct_change = (
        round((price - previous_close) / previous_close * 100, 2)
        if previous_close
        else None
    )
    return {
        "source": "ths-intraday",
        "fetchedAt": int(time.time()),
        "code": code,
        "name": data.get("name"),
        "price": price,
        "open": point_prices[0],
        "high": max(point_prices),
        "low": min(point_prices),
        "pctChange": pct_change,
        "turnoverRate": None,
        "amount": None,
        "quoteTime": data.get("date"),
        "quoteClock": latest_time,
        "previousClose": previous_close,
        "isIntraday": bool(data.get("isTrading")),
    }


def fetch_ths_intraday_quote(code, force_refresh=False, wait_for_slot=False):
    cached = read_quote_cache(code)
    if cached and cached.get("source") == "ths-intraday" and not force_refresh:
        return {"ok": True, "quote": cached, "fromCache": True}
    if wait_for_slot and not wait_for_provider_slot():
        return {"ok": False, "reason": "实时价刷新等待超时，外部请求仍在冷却。"}
    url = f"https://d.10jqka.com.cn/v6/time/hs_{code}/last.js"
    result = external_request_text(
        url,
        "同花顺盘中行情",
        f"https://stockpage.10jqka.com.cn/{code}/",
    )
    if not result.get("ok"):
        return result
    try:
        quote = parse_ths_intraday_quote(result["text"], code)
    except (ValueError, json.JSONDecodeError) as error:
        return {"ok": False, "reason": f"同花顺盘中行情解析失败：{error}"}
    if not quote:
        return {"ok": False, "reason": "同花顺盘中行情未返回有效价格。"}
    write_quote_cache(code, quote)
    return {"ok": True, "quote": quote, "fromCache": False}


def fetch_provider_quote(code, force_refresh=False, wait_for_slot=False):
    bridged = read_tdx_bridge_quote(code)
    if bridged:
        return {"ok": True, "quote": bridged, "fromCache": True, "provider": "tdx_bridge"}
    if ENABLE_EASTMONEY:
        result = fetch_eastmoney_quote(
            code,
            force_refresh=force_refresh,
            wait_for_slot=True,
        )
        if result.get("ok"):
            result["provider"] = "eastmoney"
        return result
    if code in ETF_MASTER:
        return {"ok": False, "reason": "ETF 的通达信桥接报价尚未同步。"}
    return fetch_ths_intraday_quote(
        code,
        force_refresh=force_refresh,
        wait_for_slot=wait_for_slot,
    )


def fetch_ths_klines(code, limit=520, force_refresh=False, wait_for_slot=False):
    cached = read_kline_cache(f"ths_{code}")
    if cached and not force_refresh:
        return {"ok": True, "klines": cached, "fromCache": True, "provider": "ths"}

    urls = [
        f"https://d.10jqka.com.cn/v6/line/hs_{code}/01/last{limit}.js",
        f"https://d.10jqka.com.cn/v6/line/hs_{code}/01/all.js",
        f"http://d.10jqka.com.cn/v6/line/hs_{code}/01/last{limit}.js",
    ]
    last_reason = "同花顺日K未返回可解析数据。"
    default_reason = last_reason
    for url in urls:
        if wait_for_slot and not wait_for_provider_slot():
            last_reason = "完整日K刷新等待超时，外部请求仍在冷却。"
            break
        result = external_request_text(url, "同花顺", f"https://stockpage.10jqka.com.cn/{code}/")
        if not result.get("ok"):
            reason = result.get("reason", last_reason)
            if "全局请求冷却" in reason:
                if last_reason == default_reason:
                    last_reason = reason
                break
            last_reason = reason
            continue
        try:
            klines = parse_ths_kline_payload(result["text"])
        except (ValueError, json.JSONDecodeError) as error:
            last_reason = f"同花顺日K解析失败：{error}"
            continue
        if len(klines) >= 60:
            write_kline_cache(f"ths_{code}", klines[-limit:])
            return {"ok": True, "klines": klines[-limit:], "fromCache": False, "provider": "ths"}
        last_reason = "同花顺日K数据不足，暂无法评分。"
    fallback = read_kline_cache_fallback(f"ths_{code}")
    if fallback:
        return {
            "ok": True,
            "klines": fallback[-limit:],
            "fromCache": True,
            "staleCache": True,
            "provider": "ths",
            "reason": f"{last_reason} 已回退到最近一次有效日K缓存。",
        }
    return {"ok": False, "reason": last_reason}


def fetch_provider_klines(code, force_refresh=False, wait_for_slot=False):
    bridged = read_tdx_bridge_klines(
        code,
        allow_stale=ALLOW_LAGGING_KLINE_SEED,
    )
    if bridged and ALLOW_LAGGING_KLINE_SEED:
        gap_days = kline_payload_gap_days(bridged)
        if gap_days is None or gap_days > KLINE_SEED_MAX_GAP_DAYS:
            bridged = None
    if bridged:
        return {
            "ok": True,
            "klines": bridged[-520:],
            "fromCache": True,
            "provider": "tdx_bridge",
        }
    if ENABLE_EASTMONEY:
        if wait_for_slot and not wait_for_provider_slot():
            return {"ok": False, "reason": "东财完整日K刷新等待超时，外部请求仍在冷却。"}
        result = fetch_eastmoney_klines(
            code,
            limit=520,
            force=force_refresh,
            cache_prefix="eastmoney_",
        )
        if result.get("ok"):
            result["provider"] = "eastmoney"
        return result
    if code in ETF_MASTER:
        result = fetch_eastmoney_klines(
            code,
            limit=520,
            force=force_refresh,
            cache_prefix="etf_",
        )
        if result.get("ok"):
            result["provider"] = "eastmoney_etf"
        return result
    ths_result = fetch_ths_klines(
        code,
        force_refresh=force_refresh,
        wait_for_slot=wait_for_slot,
    )
    if ths_result.get("ok"):
        return ths_result
    return {"ok": False, "reason": ths_result.get("reason")}


def merge_intraday_quote_as_latest_bar(klines, quote):
    if not klines or not quote or quote.get("price") is None or not quote.get("quoteTime"):
        return klines
    quote_date = parse_kline_date(quote.get("quoteTime"))
    last_date = parse_kline_date(klines[-1].get("date"))
    if not quote_date or not last_date or quote_date <= last_date:
        return klines

    previous_close = quote.get("previousClose") or klines[-1].get("close")
    price = quote.get("price")
    pct_change = (
        round((price - previous_close) / previous_close * 100, 2)
        if price is not None and previous_close
        else quote.get("pctChange")
    )
    synthetic_bar = {
        "date": quote_date.strftime("%Y%m%d"),
        "open": quote.get("open") or previous_close or price,
        "close": price,
        "high": quote.get("high") or max(value for value in (previous_close, price) if value is not None),
        "low": quote.get("low") or min(value for value in (previous_close, price) if value is not None),
        "volume": None,
        "amount": quote.get("amount"),
        "amplitude": None,
        "pctChange": pct_change,
        "change": round(price - previous_close, 2) if price is not None and previous_close else None,
        "turnoverRate": quote.get("turnoverRate"),
        "temporary": True,
        "source": quote.get("source"),
    }
    return [*klines, synthetic_bar]


def quote_signal(quote):
    if not quote:
        return "同花顺日K未命中缓存，当前不会额外请求其他行情源。"
    parts = []
    if quote.get("price") is not None:
        parts.append(f"当前价 {quote['price']}")
    if quote.get("pctChange") is not None:
        parts.append(f"涨跌幅 {quote['pctChange']}%")
    if quote.get("turnoverRate") is not None:
        parts.append(f"换手率 {quote['turnoverRate']}%")
    return "，".join(parts) + "。"


def average(values):
    clean = [value for value in values if value is not None]
    if not clean:
        return None
    return sum(clean) / len(clean)


def last_average(values, window):
    if len(values) < window:
        return None
    return average(values[-window:])


def average_true_range(klines, window=14):
    rows = [
        item
        for item in klines
        if item.get("high") is not None and item.get("low") is not None and item.get("close") is not None
    ]
    if len(rows) < 2:
        return None
    ranges = []
    start = max(1, len(rows) - window)
    for index in range(start, len(rows)):
        high = rows[index]["high"]
        low = rows[index]["low"]
        previous_close = rows[index - 1]["close"]
        ranges.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))
    return average(ranges)


def volume_signal(pct_change, today_ratio, volume_ratio):
    if today_ratio is None:
        return "成交量数据不足，暂不判断量价配合。"
    if pct_change is not None and pct_change > 1:
        if today_ratio >= 1.2:
            return f"上涨放量，今日量能约为20日均量 {today_ratio:.2f}x，资金确认度较好。"
        if today_ratio < 0.8:
            return f"上涨缩量，今日量能仅为20日均量 {today_ratio:.2f}x，突破确认度要打折。"
        return f"上涨量能温和，今日量能约为20日均量 {today_ratio:.2f}x。"
    if pct_change is not None and pct_change < -1:
        if today_ratio >= 1.5:
            return f"下跌放量，今日量能约为20日均量 {today_ratio:.2f}x，需警惕筹码松动。"
        return f"回调量能可控，今日量能约为20日均量 {today_ratio:.2f}x。"
    if volume_ratio is not None:
        return f"近5日/前20日量能比 {volume_ratio:.2f}x，观察是否缩量回踩后再放量转强。"
    return "量能变化不明显，继续看后续放量或缩量方向。"


def turnover_signal(turnover_rate):
    if turnover_rate is None:
        return "换手率当前源暂未稳定返回，先不把它作为硬性扣分项。"
    if turnover_rate < 1:
        return f"换手率 {turnover_rate:.2f}%，筹码交换偏低，趋势延续需要后续成交确认。"
    if turnover_rate <= 12:
        return f"换手率 {turnover_rate:.2f}%，处在趋势股相对健康区间。"
    if turnover_rate <= 20:
        return f"换手率 {turnover_rate:.2f}%，交易较热，适合等回踩确认而不是追。"
    return f"换手率 {turnover_rate:.2f}%，短线筹码交换过热，风险收益要下调。"


def parse_percent(value):
    if value in (None, False, "", "-"):
        return None
    text = str(value).replace("%", "").replace(",", "").strip()
    try:
        return float(text)
    except ValueError:
        return None


def parse_number(value):
    if value in (None, False, "", "-"):
        return None
    text = str(value).replace(",", "").strip()
    multiplier = 1
    if text.endswith("万"):
        multiplier = 10_000
        text = text[:-1]
    elif text.endswith("亿"):
        multiplier = 100_000_000
        text = text[:-1]
    try:
        return float(text) * multiplier
    except ValueError:
        return None


def parse_ths_finance_payload(text):
    match = re.search(r'<p[^>]+id=["\']main["\'][^>]*>(.*?)</p>', text, re.S)
    if not match:
        return None
    raw = html.unescape(match.group(1)).strip()
    data = json.loads(raw)
    titles = data.get("title") or []
    reports = data.get("report") or []
    if len(titles) < 2 or len(reports) < 2 or not reports[0]:
        return None

    latest = {"reportDate": reports[0][0]}
    for index, title in enumerate(titles[1:], 1):
        if index >= len(reports) or not reports[index]:
            continue
        name = title[0] if isinstance(title, list) else str(title)
        latest[name] = reports[index][0]

    return {
        "reportDate": latest.get("reportDate"),
        "netProfitYoy": parse_percent(latest.get("净利润同比增长率")),
        "deductedProfitYoy": parse_percent(latest.get("扣非净利润同比增长率")),
        "revenueYoy": parse_percent(latest.get("营业总收入同比增长率")),
        "netMargin": parse_percent(latest.get("销售净利率")),
        "grossMargin": parse_percent(latest.get("销售毛利率")),
        "roe": parse_percent(latest.get("净资产收益率")),
        "operatingCashPerShare": parse_number(latest.get("每股经营现金流")),
        "debtRatio": parse_percent(latest.get("资产负债率")),
        "source": "ths_f10_finance",
        "fetchedAt": int(time.time()),
    }


def strip_tags(value):
    return re.sub(r"<[^>]+>", "", html.unescape(value or "")).strip()


def parse_ths_theme_payload(text):
    industry = None
    industry_match = re.search(r"所属申万行业：</span>\s*<span[^>]*>(.*?)</span>", text, re.S)
    if industry_match:
        industry = strip_tags(industry_match.group(1))

    concepts = []
    concept_pattern = re.compile(
        r"onclick=\"jumpToUrl\('\./concept\.html',\s*'concept',\s*'',\s*'([^']+)'\).*?>(.*?)</a>",
        re.S,
    )
    for concept_match in concept_pattern.finditer(text):
        concept = strip_tags(concept_match.group(1)) or strip_tags(concept_match.group(2))
        if concept and concept not in concepts:
            concepts.append(concept)

    reason = None
    reason_match = re.search(r"分析或为：\s*([^<\n\r]+)", text)
    if reason_match:
        reason = strip_tags(reason_match.group(1))

    core_view = None
    core_match = re.search(r'class="tip f14 fl core-view-text"[^>]*title="([^"]+)"', text)
    if core_match:
        core_view = strip_tags(core_match.group(1))

    if not industry and not concepts and not reason:
        return None

    return {
        "industry": industry,
        "concepts": concepts[:8],
        "topConcepts": concepts[:3],
        "limitUpReason": reason,
        "coreView": core_view,
        "source": "ths_f10_theme",
        "fetchedAt": int(time.time()),
    }


def fetch_ths_theme(code):
    cached = read_theme_cache(code)
    if cached:
        return {"ok": True, "theme": cached, "fromCache": True, "provider": "ths_f10_theme"}

    url = f"https://basic.10jqka.com.cn/{code}/"
    result = external_request_text(url, "同花顺题材", f"https://stockpage.10jqka.com.cn/{code}/", encoding="gbk")
    if not result.get("ok"):
        return result
    theme = parse_ths_theme_payload(result["text"])
    if not theme:
        return {"ok": False, "reason": "同花顺 F10 未解析到行业/概念题材。"}
    write_theme_cache(code, theme)
    return {"ok": True, "theme": theme, "fromCache": False, "provider": "ths_f10_theme"}


def score_mainline(theme, trend_score, pullback_score, strength=None):
    if not theme:
        return {
            "score": 0,
            "available": False,
            "signals": [
                "主线题材暂未命中缓存，不计入总分。",
                "第一版主线只在单票搜索时低频读取同花顺 F10 行业/概念，不做全市场高频扫描。",
            ],
        }

    top_concepts = theme.get("topConcepts") or []
    concepts = theme.get("concepts") or []
    reason = theme.get("limitUpReason")

    base_score = 0
    base_score += 6 if top_concepts else 0
    base_score += min(4, len(concepts))
    base_score += 4 if reason else 0
    base_score += 3 if trend_score >= 14 else 1 if trend_score >= 10 else 0
    base_score += 3 if pullback_score >= 12 else 1 if pullback_score >= 8 else 0
    score = clamp(base_score, 0, 16)
    cap = 16
    adjustment = 0

    if strength and strength.get("available"):
        verdict = strength.get("verdict")
        priority = (strength.get("priority") or {}).get("level")
        group_gate = (strength.get("groupState") or {}).get("gate")
        stock_rps50 = ((strength.get("stockRps") or {}).get("rps50"))
        red80 = strength.get("groupRed80") or 0
        if verdict == "强股强方向" and group_gate == "允许加权":
            cap = 20
            adjustment = 4 if priority == "A" else 3
        elif verdict == "个股强于方向" and group_gate != "禁止加权":
            cap = 18
            adjustment = 1
        elif verdict == "方向强，个股待确认" and group_gate == "允许加权":
            cap = 17
            adjustment = 1 if stock_rps50 is not None and stock_rps50 >= 55 else 0
        elif stock_rps50 is not None and stock_rps50 < 40 and red80 == 0:
            cap = 14
            adjustment = -2
        score = clamp(score + adjustment, 0, cap)

    signals = [
        f"申万行业：{theme.get('industry') or '待确认'}。",
        f"贴合度前三概念：{'、'.join(top_concepts) if top_concepts else '待确认'}。",
    ]
    if reason:
        signals.append(f"近期异动题材：{reason}。")
    if strength and strength.get("available"):
        priority = strength.get("priority") or {}
        signals.append(
            f"RPS修正：{strength.get('verdict') or '待确认'}，入池优先级 {priority.get('level') or '-'} {priority.get('label') or ''}，主线分 {score}/20。"
        )
        if adjustment:
            signals.append(f"主线分从基础 {clamp(base_score, 0, 16)}/20 修正 {adjustment:+d}，当前封顶 {cap}/20。")
        else:
            signals.append(f"主线基础分 {clamp(base_score, 0, 16)}/20，RPS暂不额外加分。")
    else:
        signals.append(
            f"主线分 {score}/20：第一版按概念贴合度、异动题材、个股趋势共同评分；RPS不足时最高封顶 16 分。"
        )
    return {"score": score, "available": True, "signals": signals}


def score_growth(finance):
    revenue_yoy = finance.get("revenueYoy")
    deducted_yoy = finance.get("deductedProfitYoy")
    score = 0
    score += 5 if revenue_yoy is not None and revenue_yoy >= 20 else 4 if revenue_yoy is not None and revenue_yoy >= 10 else 2 if revenue_yoy is not None and revenue_yoy >= 0 else 0
    score += 6 if deducted_yoy is not None and deducted_yoy >= 20 else 4 if deducted_yoy is not None and deducted_yoy >= 0 else 1 if revenue_yoy is not None and revenue_yoy > 10 else 0
    return {
        "score": clamp(score, 0, 11),
        "label": "增长",
        "metrics": {
            "revenueYoy": revenue_yoy,
            "deductedProfitYoy": deducted_yoy,
        },
    }


def score_profitability(finance):
    gross_margin = finance.get("grossMargin")
    net_margin = finance.get("netMargin")
    roe = finance.get("roe")
    score = 0
    score += 5 if roe is not None and roe >= 12 else 4 if roe is not None and roe >= 8 else 2 if roe is not None and roe >= 4 else 0
    score += 4 if gross_margin is not None and gross_margin >= 30 else 3 if gross_margin is not None and gross_margin >= 15 else 1 if gross_margin is not None and gross_margin > 0 else 0
    score += 4 if net_margin is not None and net_margin >= 10 else 2 if net_margin is not None and net_margin >= 5 else 0
    return {
        "score": clamp(score, 0, 13),
        "label": "盈利质量",
        "metrics": {
            "grossMargin": gross_margin,
            "netMargin": net_margin,
            "roe": roe,
        },
    }


def score_cash_debt(finance):
    cash_ps = finance.get("operatingCashPerShare")
    debt_ratio = finance.get("debtRatio")
    score = 0
    score += 3 if cash_ps is not None and cash_ps > 0 else 0
    score += 3 if debt_ratio is not None and debt_ratio <= 45 else 2 if debt_ratio is not None and debt_ratio <= 60 else 0
    return {
        "score": clamp(score, 0, 6),
        "label": "现金流/负债",
        "metrics": {
            "operatingCashPerShare": cash_ps,
            "debtRatio": debt_ratio,
        },
    }


def expansion_stage(finance):
    revenue_yoy = finance.get("revenueYoy")
    deducted_yoy = finance.get("deductedProfitYoy")
    net_margin = finance.get("netMargin")
    gross_margin = finance.get("grossMargin")
    cash_ps = finance.get("operatingCashPerShare")
    if revenue_yoy is not None and revenue_yoy > 0 and deducted_yoy is not None and deducted_yoy < 0:
        stage = "扩产/投入承压"
        note = "营收仍增长但扣非利润为负，可能处在扩产、研发、折旧或价格压力阶段，不能简单按利润下滑一刀切。"
    elif revenue_yoy is not None and revenue_yoy >= 10 and deducted_yoy is not None and deducted_yoy >= 10:
        stage = "经营改善期"
        note = "营收和扣非利润同步改善，基本面顺风更适合趋势持有。"
    elif deducted_yoy is not None and deducted_yoy < 0:
        stage = "利润承压期"
        note = "扣非利润承压，若没有营收或现金流承接，需要降低中长期确定性。"
    else:
        stage = "财报已接入"
        note = "当前字段不足以判断明显扩产压力，先按财报质量中性处理。"

    if cash_ps is not None and cash_ps <= 0:
        note += " 经营现金流不佳时，扩产逻辑要更谨慎。"
    if gross_margin is not None and net_margin is not None and gross_margin > 0 and net_margin / gross_margin < 0.25:
        note += " 毛利到净利转化偏弱，费用、折旧或价格压力需要继续跟踪。"
    return {"stage": stage, "note": note}


def build_fundamental_quality(finance, score, stage_view):
    report_date = finance.get("reportDate")
    revenue_yoy = finance.get("revenueYoy")
    deducted_yoy = finance.get("deductedProfitYoy")
    gross_margin = finance.get("grossMargin")
    net_margin = finance.get("netMargin")
    cash_ps = finance.get("operatingCashPerShare")
    debt_ratio = finance.get("debtRatio")

    evidence = []
    gaps = []
    risks = []

    if report_date:
        evidence.append(f"已接入最新财报期 {report_date}。")
    else:
        gaps.append("缺最新财报期，不能判断数据新鲜度。")

    if revenue_yoy is not None and deducted_yoy is not None:
        if revenue_yoy > 0 and deducted_yoy > 0:
            evidence.append("营收和扣非利润同步为正，增长有初步验证。")
        elif revenue_yoy > 0 and deducted_yoy < 0:
            risks.append("营收增长但扣非利润下滑，可能是价格、费用、折旧或投入压力。")
        else:
            risks.append("营收或扣非利润未形成正向验证。")
    else:
        gaps.append("缺营收/扣非利润同比，无法验证增长质量。")

    if gross_margin is not None and net_margin is not None:
        if gross_margin > 15 and net_margin > 5:
            evidence.append("毛利率和净利率为正且具备一定转化。")
        elif gross_margin > 0 and net_margin <= 3:
            risks.append("毛利到净利转化偏弱，费用或价格压力需要跟踪。")
    else:
        gaps.append("缺毛利率/净利率，无法判断盈利转化。")

    if cash_ps is not None:
        if cash_ps > 0:
            evidence.append("经营现金流为正，基本面承接更稳。")
        else:
            risks.append("经营现金流为负，趋势持有需要降低确定性。")
    else:
        gaps.append("缺经营现金流，无法判断利润含金量。")

    if debt_ratio is not None:
        if debt_ratio <= 45:
            evidence.append("资产负债率较稳，财务压力不高。")
        elif debt_ratio >= 65:
            risks.append("资产负债率偏高，扩张或景气下行时压力会放大。")
    else:
        gaps.append("缺资产负债率，无法判断财务压力。")

    gaps.extend([
        "暂未接入在建工程/资本开支，扩产兑现节奏仍需二次验证。",
        "暂未接入客户、订单和产能利用率，产业链地位仍需人工/公告补证。",
    ])

    if score >= 22 and len(risks) == 0:
        level = "已夯实"
        action = "可作为中期跟踪底座，但买卖仍服从趋势和主线。"
    elif score >= 16 and len(evidence) >= 3:
        level = "初步夯实"
        action = "可跟踪，但需要继续验证扩产、订单和现金流持续性。"
    elif score >= 12:
        level = "待验证"
        action = "只给观察资格，不能单独支撑长期持有。"
    else:
        level = "未夯实"
        action = "基本面不支持提高仓位，反弹更多按交易处理。"

    return {
        "level": level,
        "action": action,
        "stage": stage_view.get("stage"),
        "evidence": evidence[:5],
        "gaps": gaps[:5],
        "risks": risks[:5],
    }


def score_fundamental(finance):
    if not finance:
        return {
            "score": 12,
            "stage": "待接财报",
            "breakdown": [],
            "signals": [
                "基本面暂未命中本地财报缓存，先用保守占位分。",
                "财报是低频数据，缓存过期后才会尝试同花顺 F10 单票刷新。",
                "扩产相关的在建工程、资本开支和转固节奏将在第二步接入。",
            ],
            "available": False,
        }

    growth = score_growth(finance)
    profitability = score_profitability(finance)
    cash_debt = score_cash_debt(finance)
    breakdown = [growth, profitability, cash_debt]
    score = clamp(sum(item["score"] for item in breakdown), 0, 30)
    stage_view = expansion_stage(finance)
    revenue_yoy = finance.get("revenueYoy")
    deducted_yoy = finance.get("deductedProfitYoy")
    gross_margin = finance.get("grossMargin")
    net_margin = finance.get("netMargin")
    roe = finance.get("roe")
    cash_ps = finance.get("operatingCashPerShare")
    debt_ratio = finance.get("debtRatio")

    signals = [
        f"最新财报期 {finance.get('reportDate') or '待确认'}，基本面分 {score}/30。",
        f"营收同比 {format_metric(revenue_yoy)}，扣非净利同比 {format_metric(deducted_yoy)}，ROE {format_metric(roe)}。",
        f"毛利率 {format_metric(gross_margin)}，净利率 {format_metric(net_margin)}，资产负债率 {format_metric(debt_ratio)}。",
        stage_view["note"],
    ]
    if cash_ps is not None:
        signals.append(f"每股经营现金流 {cash_ps:.2f}，现金流为正才更适合作为中长期趋势股底仓。")
    signals.append("扩产判断当前先看营收、扣非利润、利润率和现金流是否互相验证；在建工程/资本开支下一步接入。")
    quality = build_fundamental_quality(finance, score, stage_view)

    return {
        "score": score,
        "stage": stage_view["stage"],
        "breakdown": breakdown,
        "signals": signals,
        "quality": quality,
        "available": True,
    }


def format_metric(value):
    return "待接入" if value is None else f"{value:.2f}%"


def fetch_ths_fundamental(code, force_refresh=False, wait_for_slot=False):
    cached = read_fundamental_cache(code)
    if cached and not force_refresh:
        return {"ok": True, "finance": cached, "fromCache": True, "provider": "ths_f10"}

    if wait_for_slot and not wait_for_provider_slot():
        return {"ok": False, "reason": "基本面刷新等待超时，外部请求仍在冷却。"}

    url = f"https://basic.10jqka.com.cn/{code}/finance.html"
    result = external_request_text(url, "同花顺财务", f"https://stockpage.10jqka.com.cn/{code}/", encoding="gbk")
    if not result.get("ok"):
        return result
    try:
        finance = parse_ths_finance_payload(result["text"])
    except (ValueError, json.JSONDecodeError) as error:
        return {"ok": False, "reason": f"同花顺财务指标解析失败：{error}"}
    if not finance:
        return {"ok": False, "reason": "同花顺财务指标未返回主要指标。"}
    write_fundamental_cache(code, finance)
    return {"ok": True, "finance": finance, "fromCache": False, "provider": "ths_f10"}


def clamp(value, low, high):
    return max(low, min(high, value))


def provider_name(provider):
    return {
        "ths": "同花顺",
        "eastmoney": "东财",
        "eastmoney_etf": "东财ETF",
        "unknown": "行情源",
    }.get(provider, provider)


def infer_metrics_from_signals(stock):
    text = " ".join((stock.get("capacity") or {}).get("signals", []) + stock.get("buySignals", []))

    def pick(pattern):
        import re

        match = re.search(pattern, text)
        return float(match.group(1)) if match else None

    return {
        "ma20": pick(r"MA20\s*([0-9.]+)"),
        "ma60": pick(r"MA60\s*([0-9.]+)"),
        "drawdownPct": pick(r"60日(?:高点)?回撤\s*([0-9.]+)%"),
        "riskPct": pick(r"风险距离约\s*([0-9.]+)%"),
        "triggerDistancePct": pick(r"距(?:触发价|确认价|加仓确认价)约\s*([0-9.]+)%"),
        "nearMa20Pct": pick(r"距MA20约\s*([0-9.]+)%"),
        "volumeRatio5To20": pick(r"量能比\s*([0-9.]+)x"),
    }


def ensure_metrics(payload):
    stock = payload.get("stock") or {}
    if stock.get("hasScore") and not stock.get("metrics"):
        inferred = infer_metrics_from_signals(stock)
        stock["metrics"] = inferred
    metrics = stock.get("metrics") or {}
    price = stock.get("price")
    trigger = stock.get("trigger")
    if (
        stock.get("hasScore")
        and metrics.get("triggerDistancePct") is None
        and price
        and trigger
        and trigger >= price
    ):
        metrics["triggerDistancePct"] = round((trigger - price) / price * 100, 1)
        stock["metrics"] = metrics
    return payload


def period_key_for_kline(date_text, period):
    parsed = parse_kline_date(date_text)
    if not parsed:
        return None
    if period == "weekly":
        iso_year, iso_week, _ = parsed.isocalendar()
        return f"{iso_year}-W{iso_week:02d}"
    if period == "monthly":
        return f"{parsed.year}-{parsed.month:02d}"
    return str(date_text)


def aggregate_period_klines(klines, period):
    if period == "daily":
        return [item for item in klines if item.get("date") and item.get("close") is not None]

    grouped = []
    current_key = None
    current = None
    for item in klines:
        key = period_key_for_kline(item.get("date"), period)
        if not key or item.get("close") is None:
            continue
        if key != current_key:
            if current:
                grouped.append(current)
            current_key = key
            current = {
                "date": item.get("date"),
                "open": item.get("open"),
                "close": item.get("close"),
                "high": item.get("high"),
                "low": item.get("low"),
                "volume": item.get("volume") or 0,
                "amount": item.get("amount") or 0,
            }
            continue
        current["date"] = item.get("date")
        current["close"] = item.get("close")
        if item.get("high") is not None:
            current["high"] = max(current.get("high") or item["high"], item["high"])
        if item.get("low") is not None:
            current["low"] = min(current.get("low") or item["low"], item["low"])
        current["volume"] = (current.get("volume") or 0) + (item.get("volume") or 0)
        current["amount"] = (current.get("amount") or 0) + (item.get("amount") or 0)
    if current:
        grouped.append(current)
    return grouped


def classify_timeframe(label, closes, ma_fast, ma_slow, high_window, drawdown, previous_ma_fast=None):
    price = closes[-1]
    prev_price = closes[-2] if len(closes) >= 2 else price
    if not ma_fast or not ma_slow:
        return "样本不足", "观察", f"{label}样本不足，暂不放大仓位。"
    fast_above_slow = ma_fast > ma_slow
    price_above_fast = price > ma_fast
    price_above_slow = price > ma_slow
    fast_slope_up = previous_ma_fast is None or ma_fast >= previous_ma_fast

    if price_above_fast and fast_above_slow and drawdown <= 0.12 and fast_slope_up:
        phase = "主升"
        action = "顺势持有"
        reason = f"{label}价格在快慢均线上方，趋势仍由多头控制。"
    elif price_above_slow and fast_above_slow:
        phase = "上升回踩"
        action = "等日线买点"
        reason = f"{label}中期趋势仍在，但需要日线靠近支撑后再动手。"
    elif price_above_fast and not fast_above_slow:
        phase = "修复"
        action = "轻仓观察"
        reason = f"{label}价格短线修复，但快慢线尚未重新多头排列。"
    elif price < ma_fast and price < ma_slow:
        phase = "退潮"
        action = "降低仓位"
        reason = f"{label}价格跌破快慢均线，反弹先按修复看。"
    else:
        phase = "震荡"
        action = "等待确认"
        reason = f"{label}趋势分歧，先等价格重新表态。"

    if high_window and price >= high_window * 0.98 and prev_price <= price:
        reason += " 当前接近阶段新高，新增仓位要防一致性追高。"
    return phase, action, reason


def analyze_timeframe(klines, period, label, fast_window, slow_window, high_window):
    rows = aggregate_period_klines(klines, period)
    rows = [item for item in rows if item.get("close") is not None]
    min_rows = max(6, fast_window + 2)
    if len(rows) < min_rows:
        return {
            "label": label,
            "period": period,
            "available": False,
            "phase": "样本不足",
            "action": "观察",
            "price": None,
            "maFast": None,
            "maSlow": None,
            "drawdownPct": None,
            "nearFastPct": None,
            "bars": len(rows),
            "signals": [f"{label}可用K线不足，暂不作为仓位依据。"],
        }

    closes = [item["close"] for item in rows]
    highs = [item.get("high") if item.get("high") is not None else item["close"] for item in rows]
    price = closes[-1]
    ma_fast = last_average(closes, fast_window)
    previous_ma_fast = (
        average(closes[-fast_window - 1:-1])
        if len(closes) >= fast_window + 1
        else None
    )
    fallback_slow_window = max(fast_window, len(closes) // 2)
    ma_slow = last_average(closes, slow_window) if len(closes) >= slow_window else last_average(closes, fallback_slow_window)
    high_value = max(highs[-min(len(highs), high_window):])
    drawdown = (high_value - price) / high_value if high_value else 0
    near_fast = abs(price - ma_fast) / ma_fast if ma_fast else None
    phase, action, reason = classify_timeframe(
        label,
        closes,
        ma_fast,
        ma_slow,
        high_value,
        drawdown,
        previous_ma_fast,
    )
    return {
        "label": label,
        "period": period,
        "available": True,
        "phase": phase,
        "action": action,
        "price": round(price, 2),
        "maFast": round(ma_fast, 2) if ma_fast else None,
        "maSlow": round(ma_slow, 2) if ma_slow else None,
        "drawdownPct": round(drawdown * 100, 1),
        "nearFastPct": round(near_fast * 100, 1) if near_fast is not None else None,
        "bars": len(rows),
        "signals": [
            reason,
            f"{label}快线 {ma_fast:.2f}，慢线 {ma_slow:.2f}，阶段高点回撤 {drawdown * 100:.1f}%。",
        ],
    }


def build_timeframe_view(klines, execution_plan):
    daily = analyze_timeframe(klines, "daily", "日线", 20, 60, 60)
    weekly = analyze_timeframe(klines, "weekly", "周线", 10, 30, 52)
    monthly = analyze_timeframe(klines, "monthly", "月线", 6, 12, 24)

    daily["action"] = execution_plan.get("executionGate") or daily.get("action")
    daily["trialLow"] = execution_plan.get("trialLow")
    daily["trialHigh"] = execution_plan.get("trialHigh")
    daily["repairConfirmPrice"] = execution_plan.get("repairConfirmPrice")
    daily["addConfirmPrice"] = execution_plan.get("addConfirmPrice")
    daily["invalidPrice"] = execution_plan.get("invalidPrice")

    long_phase = monthly.get("phase")
    mid_phase = weekly.get("phase")
    daily_action = daily.get("action")
    if long_phase in ("主升", "上升回踩") and mid_phase in ("主升", "上升回踩"):
        verdict = "长中周期顺势，日线只等买点。"
        posture = "可按计划做波段"
    elif long_phase in ("退潮", "样本不足") or mid_phase == "退潮":
        verdict = "上级周期不支持重仓，日线信号只能轻仓试错。"
        posture = "降低仓位"
    elif mid_phase == "修复":
        verdict = "周线修复中，日线确认后再加仓。"
        posture = "轻仓观察"
    else:
        verdict = "三周期尚未共振，先等价格确认。"
        posture = "等待确认"

    if daily_action in ("等待低吸位", "等待恐慌触发", "等待衰竭", "等待回收", "禁止买入", "等待修复"):
        verdict += f" 当前日线动作是{daily_action}。"

    return {
        "verdict": verdict,
        "posture": posture,
        "daily": daily,
        "weekly": weekly,
        "monthly": monthly,
        "signals": [
            f"月线：{monthly.get('phase')}，{monthly.get('action')}。",
            f"周线：{weekly.get('phase')}，{weekly.get('action')}。",
            f"日线：{daily.get('phase')}，{daily.get('action')}。",
            verdict,
        ],
    }


def cluster_trade_levels(candidates, tolerance, atr, current_price, side):
    eligible = [
        item for item in candidates
        if isinstance(item.get("price"), (int, float))
        and item["price"] > 0
        and (
            item["price"] >= current_price - tolerance
            if side == "pressure"
            else item["price"] <= current_price + tolerance
        )
    ]
    clusters = []
    for item in sorted(eligible, key=lambda entry: entry["price"]):
        target = next(
            (cluster for cluster in reversed(clusters) if abs(item["price"] - cluster["center"]) <= tolerance),
            None,
        )
        if target is None:
            target = {"items": [], "center": item["price"]}
            clusters.append(target)
        target["items"].append(item)
        total_weight = sum(entry.get("weight", 1) for entry in target["items"])
        target["center"] = sum(
            entry["price"] * entry.get("weight", 1) for entry in target["items"]
        ) / total_weight

    results = []
    for cluster in clusters:
        center = cluster["center"]
        half_width = max(atr * 0.22, center * 0.004)
        timeframes = list(dict.fromkeys(
            item.get("timeframe") for item in cluster["items"] if item.get("timeframe")
        ))
        kinds = list(dict.fromkeys(item.get("kind") for item in cluster["items"] if item.get("kind")))
        sources = list(dict.fromkeys(item.get("label") for item in cluster["items"] if item.get("label")))
        raw_score = (
            sum(item.get("weight", 1) for item in cluster["items"])
            + max(0, len(timeframes) - 1) * 1.5
            + max(0, len(kinds) - 1) * 0.75
        )
        grade = "S" if raw_score >= 10 else "A" if raw_score >= 7 else "B" if raw_score >= 4 else "C"
        results.append({
            "center": round(center, 2),
            "low": round(center - half_width, 2),
            "high": round(center + half_width, 2),
            "score": round(raw_score, 1),
            "grade": grade,
            "timeframes": timeframes,
            "kinds": kinds,
            "sources": sources[:6],
            "distancePct": round((center - current_price) / current_price * 100, 1) if current_price else None,
        })
    return results


def timeframe_trade_level_candidates(klines, period, label, lookback, base_weight, timeframe_view):
    rows = aggregate_period_klines(klines, period)
    rows = [row for row in rows if row.get("close") is not None]
    rows = rows[-min(len(rows), lookback):]
    if len(rows) < 8:
        return [], []

    highs = [row.get("high") if row.get("high") is not None else row["close"] for row in rows]
    lows = [row.get("low") if row.get("low") is not None else row["close"] for row in rows]
    swing_high = max(highs)
    swing_low = min(lows)
    swing_range = swing_high - swing_low
    pressures = []
    supports = []

    if swing_range > 0:
        for ratio, ratio_label in ((0.382, "38.2%"), (0.5, "50%"), (0.618, "61.8%"), (0.786, "78.6%")):
            level = swing_low + swing_range * ratio
            entry = {
                "price": level,
                "label": f"{label}斐波那契{ratio_label}",
                "timeframe": label,
                "kind": "斐波那契",
                "weight": base_weight + (0.7 if ratio in (0.5, 0.618) else 0.3),
            }
            pressures.append(entry)
            supports.append(entry)
        for ratio, ratio_label in ((0.272, "127.2%"), (0.618, "161.8%")):
            pressures.append({
                "price": swing_high + swing_range * ratio,
                "label": f"{label}斐波那契扩展{ratio_label}",
                "timeframe": label,
                "kind": "斐波那契扩展",
                "weight": base_weight + 0.2,
            })

    radius = 2 if period == "daily" else 1
    pivot_highs = []
    pivot_lows = []
    for index in range(radius, len(rows) - radius):
        high = highs[index]
        low = lows[index]
        if high >= max(highs[index - radius:index + radius + 1]):
            pivot_highs.append((index, high))
        if low <= min(lows[index - radius:index + radius + 1]):
            pivot_lows.append((index, low))
    for index, value in pivot_highs[-5:]:
        pressures.append({
            "price": value,
            "label": f"{label}前高",
            "timeframe": label,
            "kind": "结构前高",
            "weight": base_weight + index / max(1, len(rows) - 1),
        })
    for index, value in pivot_lows[-4:]:
        supports.append({
            "price": value,
            "label": f"{label}平台低点",
            "timeframe": label,
            "kind": "结构支撑",
            "weight": base_weight + index / max(1, len(rows) - 1) * 0.7,
        })

    for key, ma_label in (("maFast", "快线"), ("maSlow", "慢线")):
        value = (timeframe_view or {}).get(key)
        if isinstance(value, (int, float)):
            entry = {
                "price": value,
                "label": f"{label}{ma_label}",
                "timeframe": label,
                "kind": "均线",
                "weight": base_weight,
            }
            pressures.append(entry)
            supports.append(entry)
    return pressures, supports


def daily_volume_pressure_candidates(klines, price, atr):
    rows = [row for row in klines[-120:] if row.get("close") is not None]
    bin_size = max(atr * 0.55, price * 0.015, 0.01)
    buckets = {}
    for row in rows:
        high = row.get("high") if row.get("high") is not None else row["close"]
        low = row.get("low") if row.get("low") is not None else row["close"]
        typical = (high + low + row["close"]) / 3
        bucket = round(typical / bin_size) * bin_size
        weight = row.get("amount") or row.get("volume") or 0
        buckets[bucket] = buckets.get(bucket, 0) + max(0, weight)
    if not buckets:
        return []
    maximum = max(buckets.values()) or 1
    return [
        {
            "price": level,
            "label": "日K成交重心",
            "timeframe": "日线",
            "kind": "成交密集",
            "weight": 2 + amount / maximum * 2,
        }
        for level, amount in sorted(buckets.items(), key=lambda item: item[1], reverse=True)[:8]
    ]


def evaluate_pressure_acceptance(clusters, price, atr, latest_bar, previous_bar):
    """Describe how price is interacting with the nearest relevant pressure zone."""
    if not clusters:
        return {"state": "待形成", "detail": "暂无可验证的压力区。", "tone": "neutral", "cluster": None}

    proximity = max(atr * 1.5, price * 0.05)
    nearby = [cluster for cluster in clusters if abs(cluster["center"] - price) <= proximity]
    if not nearby:
        return {"state": "未触及", "detail": "价格尚未接近有效压力区。", "tone": "neutral", "cluster": None}

    cluster = min(nearby, key=lambda item: abs(item["center"] - price))
    low = cluster["low"]
    high = cluster["high"]
    previous_close = previous_bar.get("close") if previous_bar else None
    latest_low = latest_bar.get("low") or price
    latest_high = latest_bar.get("high") or price

    if previous_close is not None and previous_close > high and price < low:
        return {
            "state": "突破失败",
            "detail": "前一交易日曾站上压力区，但最新收盘跌回区间下沿，按受阻处理。",
            "tone": "risk",
            "cluster": cluster,
        }
    if previous_close is not None and previous_close > high and latest_low <= high and price > high:
        return {
            "state": "回踩守住",
            "detail": "突破后回踩压力区上沿但收盘仍在其上，承接暂时有效。",
            "tone": "good",
            "cluster": cluster,
        }
    if previous_close is not None and previous_close <= high and price > high:
        return {
            "state": "首次收复",
            "detail": "最新收盘首次越过压力区上沿，需下一交易日确认而非立即视为有效突破。",
            "tone": "watch",
            "cluster": cluster,
        }
    if low <= price <= high:
        return {
            "state": "区间测试",
            "detail": "收盘仍在压力区内，尚未证明突破有效。",
            "tone": "watch",
            "cluster": cluster,
        }
    if latest_high >= low and price < low:
        return {
            "state": "触压回落",
            "detail": "盘中触及压力区但收盘未进入，先按受阻观察。",
            "tone": "risk",
            "cluster": cluster,
        }
    return {"state": "未触及", "detail": "价格尚未触及最近压力区。", "tone": "neutral", "cluster": cluster}


def build_swing_exit_plan(klines, timeframe_view, strength_view, price, atr, latest_bar, volume_ratio):
    tolerance = max(atr * 0.5, price * 0.012)
    pressure_candidates = []
    support_candidates = []
    for period, label, lookback, weight in (
        ("daily", "日线", 120, 1.8),
        ("weekly", "周线", 78, 3.0),
        ("monthly", "月线", 36, 4.2),
    ):
        pressures, supports = timeframe_trade_level_candidates(
            klines, period, label, lookback, weight, (timeframe_view or {}).get(period)
        )
        pressure_candidates.extend(pressures)
        support_candidates.extend(supports)
    pressure_candidates.extend(daily_volume_pressure_candidates(klines, price, atr))

    daily_rows = [row for row in klines if row.get("close") is not None]
    prior_rows = daily_rows[:-1]
    for window, weight in ((5, 1.4), (10, 1.8), (20, 2.1)):
        sample = prior_rows[-window:]
        sample_lows = [row.get("low") for row in sample if row.get("low") is not None]
        if sample_lows:
            support_candidates.append({
                "price": min(sample_lows),
                "label": f"{window}日近期低点",
                "timeframe": "日线",
                "kind": "近期支撑",
                "weight": weight,
            })
        sample_closes = [row.get("close") for row in daily_rows[-window:] if row.get("close") is not None]
        if sample_closes:
            support_candidates.append({
                "price": average(sample_closes),
                "label": f"MA{window}",
                "timeframe": "日线",
                "kind": "短期均线",
                "weight": weight,
            })
    latest_low = latest_bar.get("low")
    if isinstance(latest_low, (int, float)) and latest_low < price:
        support_candidates.append({
            "price": latest_low,
            "label": "当日低点（待确认）",
            "timeframe": "日线",
            "kind": "战术保护",
            "weight": 1.0,
        })

    pressure_clusters = cluster_trade_levels(pressure_candidates, tolerance, atr, price, "pressure")
    previous_bar = daily_rows[-2] if len(daily_rows) >= 2 else {}
    acceptance = evaluate_pressure_acceptance(
        pressure_clusters,
        price,
        atr,
        latest_bar,
        previous_bar,
    )
    levels = sorted(
        (cluster for cluster in pressure_clusters if cluster["high"] >= price),
        key=lambda cluster: cluster["center"],
    )[:3]
    raw_support_clusters = cluster_trade_levels(support_candidates, tolerance, atr, price, "support")
    support_clusters = []
    protection_ceiling = round(price - max(price * 0.001, 0.01), 2)
    for cluster in raw_support_clusters:
        if cluster["center"] >= price:
            continue
        adjusted = {**cluster, "high": min(cluster["high"], protection_ceiling)}
        if adjusted["low"] <= adjusted["high"]:
            support_clusters.append(adjusted)
    support_clusters = sorted(
        support_clusters,
        key=lambda cluster: cluster["center"],
        reverse=True,
    )
    protection = support_clusters[0] if support_clusters else None

    strong_phases = {"主升", "上升回踩"}
    phase_map = {
        key: ((timeframe_view or {}).get(key) or {}).get("phase")
        for key in ("daily", "weekly", "monthly")
    }
    strong_count = sum(phase in strong_phases for phase in phase_map.values())
    if strong_count == 3:
        timeframe_resonance = "日周月多头共振"
    elif phase_map.get("weekly") in strong_phases and phase_map.get("monthly") in strong_phases:
        timeframe_resonance = "周月顺势，日线分歧"
    elif phase_map.get("weekly") == "退潮" or phase_map.get("monthly") == "退潮":
        timeframe_resonance = "上级周期退潮"
    else:
        timeframe_resonance = "三周期尚未共振"

    group_state = (strength_view or {}).get("groupState") or {}
    sector = (strength_view or {}).get("sectorThesis") or {}
    top_risk = (strength_view or {}).get("stageTopRisk") or {}
    sector_supportive = (
        group_state.get("trend") in ("主升", "上升")
        and sector.get("phase") not in ("退潮", "降温")
        and top_risk.get("level") != "high"
    )
    sector_weak = (
        group_state.get("gate") == "禁止加权"
        or sector.get("phase") in ("退潮", "降温")
        or top_risk.get("level") == "high"
    )
    group_name = (strength_view or {}).get("group") or "板块"
    sector_resonance = (
        f"{group_name}顺势" if sector_supportive
        else f"{group_name}退潮/高风险" if sector_weak
        else f"{group_name}等待确认"
    )

    bar_high = latest_bar.get("high") or price
    bar_low = latest_bar.get("low") or price
    bar_open = latest_bar.get("open") or price
    bar_range = max(0.01, bar_high - bar_low)
    upper_shadow_ratio = max(0, bar_high - max(bar_open, price)) / bar_range
    pct_change = latest_bar.get("pctChange")
    nearest = levels[0] if levels else None
    state = "新高区，等待新压力形成"
    action = "使用动态保护位持有，不按固定目标机械清仓。"
    if nearest:
        if nearest["low"] <= price <= nearest["high"]:
            if upper_shadow_ratio >= 0.32 or (pct_change is not None and pct_change < 0):
                state = "到压受阻"
                action = "先兑现20%-30%；若板块同步转弱，可提高到30%-50%。"
            elif volume_ratio is not None and volume_ratio >= 1.15 and price >= nearest["center"]:
                state = "放量尝试通过"
                action = "不急于卖完，等待次日站稳压力区上沿，再上移保护位。"
            else:
                state = "进入压力区"
                action = "观察收盘位置与次日承接，未站稳时分批兑现。"
        elif nearest["low"] - price <= max(atr * 0.7, price * 0.02):
            state = "接近第一压力"
            action = "提前制定分批计划，不在盘中第一次触价时一次卖完。"
        else:
            state = "尚未到达压力"
            action = "按趋势持有，临近第一压力区后再观察量价承接。"

    acceptance_state = acceptance.get("state")
    if acceptance_state == "突破失败":
        state = "突破失败"
        action = "压力突破失败，先兑现30%-50%；剩余仓位不得下移动态保护位。"
    elif acceptance_state == "回踩守住":
        state = "突破后承接"
        action = "回踩压力区上沿后收盘守住，可继续持有并把保护位上移至突破区下沿。"
    elif acceptance_state == "首次收复":
        state = "突破待确认"
        action = "收盘首次站上压力区，等待下一交易日守住上沿；确认前不因突破追加仓位。"
    elif acceptance_state == "触压回落":
        state = "到压受阻"
        action = "盘中触压后收盘回落，先兑现20%-30%，观察板块次日能否重新共振。"

    if sector_weak and state in ("进入压力区", "接近第一压力", "到压受阻"):
        action = "板块共振偏弱，到压优先兑现30%-50%，剩余仓位用动态保护位跟踪。"
    elif sector_supportive and strong_count == 3 and state in ("进入压力区", "接近第一压力"):
        action = "日周月与板块顺势，首次到压只观察承接；确认受阻后再减20%-30%。"

    reductions = ("受阻减20%-30%", "受阻再减30%-40%", "高位受阻处理剩余波段仓")
    for index, level in enumerate(levels):
        level["name"] = f"P{index + 1}压力"
        level["suggestion"] = reductions[index]
        if level["low"] <= price <= level["high"]:
            level["interaction"] = "测试中"
        elif price > level["high"]:
            level["interaction"] = "已越过"
        else:
            level["interaction"] = "未触及"

    protection_text = f"{protection['low']:.2f}-{protection['high']:.2f}" if protection else "待形成"
    return {
        "available": bool(levels),
        "state": state,
        "action": action,
        "timeframeResonance": timeframe_resonance,
        "sectorResonance": sector_resonance,
        "acceptance": {
            "state": acceptance.get("state"),
            "detail": acceptance.get("detail"),
            "tone": acceptance.get("tone"),
        },
        "levels": levels,
        "protection": protection,
        "signals": [
            "斐波那契仅作为结构证据；必须与前高、均线、成交重心或更高周期重合后才提高等级。",
            f"周期共振：{timeframe_resonance}；板块共振：{sector_resonance}。",
            f"当前状态：{state}。{action}",
            f"压力承接：{acceptance.get('state')}。{acceptance.get('detail')}",
            f"动态保护区：{protection_text}；有效跌破后优先保护波段利润，不向下放宽卖出纪律。",
            "放量突破压力区并不等于立即卖出；次日站稳上沿、回踩缩量时可继续持有。",
        ],
    }


def technical_payload(stock, klines, provider="unknown", fundamental=None, theme=None):
    closes = [item["close"] for item in klines if item["close"] is not None]
    highs = [item["high"] for item in klines if item["high"] is not None]
    lows = [item["low"] for item in klines if item["low"] is not None]
    volumes = [item["volume"] for item in klines if item["volume"] is not None]
    if len(closes) < 60 or len(highs) < 60 or len(lows) < 60:
        return pending_payload(stock, f"已识别 {stock['code']} {stock['name']}，日K数据不足，暂不生成评分。")

    latest = klines[-1]
    previous = klines[-2] if len(klines) >= 2 else {}
    price = latest["close"]
    ma5 = last_average(closes, 5)
    ma20 = last_average(closes, 20)
    ma60 = last_average(closes, 60)
    prev_ma20 = average(closes[-25:-5])
    high_60 = max(highs[-60:])
    low_20 = min(lows[-20:])
    low_10 = min(lows[-10:])
    prior_lows = [item["low"] for item in klines[:-1] if item.get("low") is not None]
    prior_low_10 = min(prior_lows[-10:]) if len(prior_lows) >= 10 else None
    prior_low_20 = min(prior_lows[-20:]) if len(prior_lows) >= 20 else None
    atr14 = average_true_range(klines, 14) or price * 0.025
    drawdown = (high_60 - price) / high_60 if high_60 else 0
    near_ma20 = abs(price - ma20) / ma20 if ma20 else 1
    volume_5 = last_average(volumes, 5) or 0
    volume_20_prev = average(volumes[-25:-5]) or volume_5 or 1
    volume_20 = last_average(volumes, 20) or volume_20_prev or 1
    latest_volume = latest.get("volume")
    volume_ratio_5_20 = volume_5 / volume_20_prev if volume_20_prev else None
    today_volume_ratio_20 = latest_volume / volume_20 if latest_volume and volume_20 else None
    support_view = build_support_view(
        price,
        ma20,
        ma60,
        low_10,
        low_20,
        atr=atr14,
        prior_low_10=prior_low_10,
        prior_low_20=prior_low_20,
    )

    trend_score = 0
    trend_score += 6 if price > ma20 else 2 if price > ma60 else 0
    trend_score += 5 if ma20 and ma60 and ma20 > ma60 else 0
    trend_score += 4 if ma20 and prev_ma20 and ma20 > prev_ma20 else 0
    trend_score += 3 if price / high_60 > 0.88 else 1 if price / high_60 > 0.78 else 0
    trend_score += 2 if ma5 and ma20 and ma5 > ma20 else 0
    trend_score = clamp(trend_score, 0, 20)

    pullback_score = 0
    pullback_score += 4 if 0.04 <= drawdown <= 0.25 else 2 if drawdown <= 0.35 else 0
    if support_view.get("available"):
        trial_low = support_view["trialLow"]
        trial_high = support_view["trialHigh"]
        if trial_low <= price <= trial_high:
            pullback_score += 8
        elif price > trial_high:
            distance_atr = (price - trial_high) / atr14 if atr14 else 99
            pullback_score += 6 if distance_atr <= 0.5 else 3 if distance_atr <= 1.2 else 0
        elif price >= support_view["invalidPrice"]:
            pullback_score += 4
    pullback_score += 4 if volume_5 <= volume_20_prev * 1.15 else 1
    if support_view.get("available"):
        latest_low = latest.get("low") or price
        if latest_low <= support_view["panicTriggerPrice"] and price >= support_view["reclaimConfirmPrice"]:
            pullback_score += 4
        elif latest.get("pctChange", 0) and latest["pctChange"] > 0:
            pullback_score += 2
    pullback_score = clamp(pullback_score, 0, 20)

    invalid = support_view["invalidPrice"]
    trigger = support_view.get("secondConfirmPrice")
    risk_pct = (price - invalid) / price if price and invalid is not None else None
    reward_pct = (high_60 - price) / price if price else 0
    trigger_distance_pct = (trigger - price) / price if price and trigger is not None and trigger >= price else None
    risk_score = 0
    if risk_pct is not None and risk_pct >= 0:
        risk_score += 4 if risk_pct <= 0.08 else 2 if risk_pct <= 0.13 else 0
        risk_score += 3 if reward_pct >= risk_pct * 1.5 else 1 if reward_pct >= risk_pct else 0
    turnover_rate = latest.get("turnoverRate")
    if turnover_rate is not None and turnover_rate <= 0:
        turnover_rate = None
    if turnover_rate is None:
        risk_score += 1
    else:
        risk_score += 3 if 1 <= turnover_rate <= 12 else 2 if turnover_rate < 18 else 0
    risk_score = clamp(risk_score, 0, 10)

    fundamental_view = score_fundamental(fundamental)
    fundamental_score = fundamental_view["score"]
    strength_view = build_strength_view(stock, klines, theme)
    mainline_view = score_mainline(theme, trend_score, pullback_score, strength_view)
    industry_score = mainline_view["score"]
    sentiment = market_sentiment_status(refresh=False)
    total = fundamental_score + industry_score + trend_score + pullback_score + risk_score
    pool_score = fundamental_score + industry_score
    entry_score = trend_score + pullback_score + risk_score
    data_stale = provider not in ("backtest", "fit", "audit") and is_stale_kline_payload(klines)
    execution_plan = build_execution_plan(
        price,
        support_view,
        trigger,
        entry_score,
        strength_view,
        sentiment,
        latest,
        ma20,
        previous_bar=previous,
        today_volume_ratio_20=today_volume_ratio_20,
        data_stale=data_stale,
    )
    timeframe_view = build_timeframe_view(klines, execution_plan)
    swing_exit_plan = build_swing_exit_plan(
        klines,
        timeframe_view,
        strength_view,
        price,
        atr14,
        latest,
        today_volume_ratio_20,
    )
    decision_loop = build_decision_loop(
        fundamental_view,
        strength_view,
        timeframe_view,
        execution_plan,
        sentiment,
    )

    if execution_plan["executionGate"] in (
        "禁止买入",
        "等待低吸位",
        "等待恐慌触发",
        "等待衰竭",
        "等待回收",
        "等待修复",
    ):
        setup_type = "观察"
        reasons = execution_plan.get("blockReasons") or []
        setup = (
            f"{execution_plan['executionGate']}：{'；'.join(reasons)}"
            if reasons
            else f"{execution_plan['executionGate']}：当前不满足执行条件"
        )
    elif execution_plan["executionGate"] == "允许轻仓试错":
        setup_type = "低点确认"
        setup = "低位抛压完成释放，并通过次日不创新低确认"
    elif execution_plan["executionGate"] == "允许极小仓低吸":
        setup_type = "最低点博弈"
        setup = "强主线低位出现抛压衰竭，只允许极小仓验证"
    else:
        setup_type = "观察"
        setup = "趋势或回调条件尚未完整，先观察低点回收与二次确认"

    quote = {
        "source": f"{provider}-kline",
        "fetchedAt": int(time.time()),
        "code": stock["code"],
        "name": stock["name"],
        "price": price,
        "pctChange": latest.get("pctChange"),
        "turnoverRate": turnover_rate,
        "amount": latest.get("amount"),
        "quoteTime": latest.get("date"),
    }
    display_industry = (
        strength_view.get("group")
        if strength_view.get("available") and strength_view.get("group") != "未匹配"
        else (theme.get("industry") if theme else stock.get("industry"))
    )
    metrics = {
        "ma5": round(ma5, 2) if ma5 else None,
        "ma20": round(ma20, 2) if ma20 else None,
        "ma60": round(ma60, 2) if ma60 else None,
        "high60": round(high_60, 2),
        "low20": round(low_20, 2),
        "drawdownPct": round(drawdown * 100, 1),
        "nearMa20Pct": round(near_ma20 * 100, 1),
        "riskPct": round(risk_pct * 100, 1) if risk_pct is not None else None,
        "rewardPct": round(reward_pct * 100, 1),
        "triggerDistancePct": round(trigger_distance_pct * 100, 1) if trigger_distance_pct is not None else None,
        "trialLow": execution_plan["trialLow"],
        "trialHigh": execution_plan["trialHigh"],
        "trialDistancePct": execution_plan["trialDistancePct"],
        "atr14": round(atr14, 2),
        "volume": latest_volume,
        "amount": latest.get("amount"),
        "turnoverRate": turnover_rate,
        "volumeMa5": round(volume_5, 0) if volume_5 else None,
        "volumeMa20": round(volume_20, 0) if volume_20 else None,
        "volumeRatio5To20": round(volume_ratio_5_20, 2) if volume_ratio_5_20 is not None else None,
        "todayVolumeRatio20": round(today_volume_ratio_20, 2) if today_volume_ratio_20 is not None else None,
        "dataStale": data_stale,
    }
    trader_checklist = build_trader_checklist(
        total,
        fundamental_view,
        strength_view,
        timeframe_view,
        execution_plan,
        latest,
        metrics,
    )

    return {
        "status": f"已用{provider_name(provider)}日K生成技术评分：{stock['code']} {stock['name']}。基本面{'已接同花顺F10' if fundamental_view['available'] else '仍为保守占位'}，主线{'使用本地板块快照' if strength_view.get('available') else '待本地板块匹配'}。",
        "source": f"{provider}_kline",
        "stock": {
            **stock,
            "industry": display_industry,
            "theme": theme,
            "marketSentiment": sentiment if sentiment.get("ok") else None,
            "strength": strength_view,
            "timeframes": timeframe_view,
            "swingExitPlan": swing_exit_plan,
            "analysisMeta": {
                "computedAt": now_text(),
                "priceAsOf": latest.get("date"),
                "klineAsOf": previous.get("date") if latest.get("temporary") else latest.get("date"),
                "provisional": bool(latest.get("temporary")),
                "levelBasis": "盘中动态，收盘待确认" if latest.get("temporary") else "完整日K确认",
                "inputs": ["日线", "周线", "月线", "板块强度", "斐波那契", "结构前高", "成交密集区"],
            },
            "decisionLoop": decision_loop,
            "traderChecklist": trader_checklist,
            "fundamental": fundamental_view,
            "hasScore": True,
            "setup": setup,
            "setupType": setup_type,
            "price": price,
            "trigger": trigger,
            "addConfirmPrice": trigger,
            "trialRange": {
                "low": execution_plan["trialLow"],
                "high": execution_plan["trialHigh"],
                "status": execution_plan["trialStatus"],
                "distancePct": execution_plan["trialDistancePct"],
            },
            "executionPlan": execution_plan,
            "invalid": invalid,
            "trend": closes[-80:],
            "klines": [
                {
                    "date": item.get("date"),
                    "close": item.get("close"),
                }
                for item in klines[-520:]
                if item.get("date") and item.get("close") is not None
            ],
            "quote": quote,
            "metrics": metrics,
            "scores": {
                "基本面与扩产质量": fundamental_score,
                "行业/主线景气度": industry_score,
                "趋势强度": trend_score,
                "回调买点质量": pullback_score,
                "估值与风险收益比": risk_score,
            },
            "poolScore": pool_score,
            "entryScore": entry_score,
            "capacity": {
                "stage": fundamental_view["stage"],
                "signals": [
                    *fundamental_view["signals"],
                    *mainline_view["signals"],
                    f"MA20 {ma20:.2f}，MA60 {ma60:.2f}，60日高点回撤 {drawdown * 100:.1f}%。",
                ],
            },
            "buySignals": [
                *execution_plan["signals"],
                f"距MA20约 {near_ma20 * 100:.1f}%，5日/20日量能比 {volume_ratio_5_20:.2f}x。",
                *timeframe_view["signals"],
                volume_signal(latest.get("pctChange"), today_volume_ratio_20, volume_ratio_5_20),
                turnover_signal(turnover_rate),
                f"趋势分 {trend_score}/20，流动性买点分 {pullback_score}/20，风险收益分 {risk_score}/10。",
                "选股质量与买点时机已经分离；必须先通过数据新鲜度、板块状态、流动性低点和次日确认，才允许提高仓位。"
                if mainline_view["available"]
                else "选股质量与买点时机已经分离；行业主线未确认时不产生主动加仓动作。",
            ],
        },
    }


def pending_payload(stock, status, quote=None, quote_note=None):
    return {
        "status": status,
        "source": "stock_master+quote_cache" if quote else "stock_master",
        "stock": {
            "code": stock["code"],
            "name": quote.get("name") or stock["name"] if quote else stock["name"],
            "industry": stock["industry"],
            "market": stock["market"],
            "hasScore": False,
            "setup": "已识别代码，等待真实行情后计算趋势、主线和流动性买点",
            "setupType": "待评估",
            "price": quote.get("price") if quote else None,
            "trigger": None,
            "invalid": None,
            "trend": [],
            "quote": quote,
            "scores": {
                "基本面与扩产质量": None,
                "行业/主线景气度": None,
                "趋势强度": None,
                "回调买点质量": None,
                "估值与风险收益比": None,
            },
            "poolScore": None,
            "entryScore": None,
            "capacity": {
                "stage": "待接财报",
                "signals": [
                    "后端已从股票基础表识别该股票，但尚未接入真实行情和财报。",
                    quote_note or quote_signal(quote),
                    "真实版本会读取营收、扣非利润、现金流、在建工程、固定资产和资本开支。",
                    "未接入财报前不生成买入评分，避免把数据不足误读为股票强弱。",
                ],
            },
            "buySignals": [
                "等待日线、周线、成交量和板块强度数据后识别流动性低点。",
                "同一股票短时间重复搜索会先复用 K 线/行情缓存。",
                "缓存失效后才进入外部数据源限速队列，避免高频请求导致 IP 风险。",
            ],
        },
    }


def evaluate_stock(
    query,
    refresh_quote=False,
    refresh_fundamental=False,
    refresh_kline=False,
    use_intraday=True,
):
    stock = find_stock(query)
    if not stock:
        clean_query = query.strip()
        is_name_like = any("\u4e00" <= char <= "\u9fff" for char in clean_query)
        status = (
            f"基础表暂未收录“{query}”。如果知道代码，先输入 6 位代码即可评分。"
            if is_name_like
            else f"没有找到“{query}”。建议输入 6 位 A 股代码，或先试 300750、300308、002594、601899。"
        )
        return {
            "status": status,
            "source": "stock_master",
            "stock": {
                "code": "未识别",
                "name": query or "未输入股票",
                "industry": "请输入 6 位代码",
                "market": "未知",
                "hasScore": False,
                "setup": "输入格式未匹配，无法进入股票评估",
                "setupType": "无法评估",
                "price": None,
                "trigger": None,
                "invalid": None,
                "trend": [],
                "scores": {
                    "基本面与扩产质量": None,
                    "行业/主线景气度": None,
                    "趋势强度": None,
                    "回调买点质量": None,
                    "估值与风险收益比": None,
                },
                "poolScore": None,
                "entryScore": None,
                "capacity": {
                    "stage": "无法评估",
                    "signals": [
                        "当前只支持本地基础表内的简称检索，以及任意 6 位 A 股代码检索。",
                        "如果简称搜不到，输入 6 位代码可以先进入同花顺日K评分。",
                        "系统不会自动替换近似简称，避免误评错误标的。",
                    ],
                },
                "buySignals": [
                    "没有有效代码，无法计算计划低吸区、回收确认价和失效价。",
                    "先确认股票简称或输入 6 位代码，再进入同花顺日K评分。",
                    "后续可以做搜索下拉框，但不做自动纠错替换。",
                ],
            },
        }

    intraday_result = None
    if refresh_quote:
        intraday_result = fetch_provider_quote(
            stock["code"],
            force_refresh=True,
            wait_for_slot=True,
        )

    kline_result = fetch_provider_klines(
        stock["code"],
        force_refresh=refresh_kline,
        wait_for_slot=refresh_kline,
    )
    if kline_result.get("ok"):
        if intraday_result is None and use_intraday:
            intraday_result = fetch_provider_quote(stock["code"])
        scoring_klines = kline_result["klines"]
        if intraday_result and intraday_result.get("ok"):
            scoring_klines = merge_intraday_quote_as_latest_bar(
                scoring_klines,
                intraday_result["quote"],
            )
        if stock.get("isETF"):
            fundamental_result = {"ok": False, "reason": "ETF不读取个股F10，按指数日K评估趋势和买点。"}
            theme_result = {"ok": False, "reason": "ETF不读取个股题材，按跟踪方向和日K评估。"}
            fundamental = None
            theme = {
                "industry": stock.get("industry"),
                "concepts": ["半导体设备", "半导体材料", "国产替代", "ETF"],
                "coreView": "ETF按指数趋势和成分方向评估，不使用个股基本面。",
            }
        elif refresh_kline:
            fundamental = read_fundamental_cache(stock["code"])
            theme = read_theme_cache(stock["code"])
            fundamental_result = {
                "ok": bool(fundamental),
                "reason": "本次只补齐K线，基本面沿用本地缓存。",
            }
            theme_result = {
                "ok": bool(theme),
                "reason": "本次只补齐K线，题材沿用本地缓存。",
            }
        else:
            fundamental_result = fetch_ths_fundamental(
                stock["code"],
                force_refresh=refresh_fundamental,
                wait_for_slot=refresh_fundamental,
            )
            fundamental = fundamental_result.get("finance") if fundamental_result.get("ok") else None
            theme_result = fetch_ths_theme(stock["code"])
            theme = theme_result.get("theme") if theme_result.get("ok") else None
        payload = technical_payload(
            stock,
            scoring_klines,
            provider=kline_result.get("provider", "unknown"),
            fundamental=fundamental,
            theme=theme,
        )
        if intraday_result and intraday_result.get("ok"):
            intraday_quote = intraday_result["quote"]
            intraday_quote["scoreDate"] = payload["stock"]["quote"].get("quoteTime")
            payload["stock"]["quote"] = intraday_quote
        elif refresh_quote and intraday_result and intraday_result.get("reason"):
            payload["stock"]["capacity"]["signals"].insert(0, f"实时价刷新失败：{intraday_result['reason']}")
        if not stock.get("isETF") and not fundamental and fundamental_result.get("reason"):
            payload["stock"]["capacity"]["signals"].insert(1, fundamental_result["reason"])
        if not stock.get("isETF") and not theme and theme_result.get("reason"):
            payload["stock"]["capacity"]["signals"].insert(2, theme_result["reason"])
        return ensure_metrics(payload)

    if stock["code"] in DEMO_SCORES:
        demo = DEMO_SCORES[stock["code"]]
        payload = {
            "status": (
                f"已识别 {stock['code']} {stock['name']}，真实日K暂不可用；"
                "当前仅显示离线样例，不产生买入动作。"
            ),
            "source": "demo_scores_fallback",
            "stock": {
                **stock,
                **demo,
                "hasScore": False,
                "quote": None,
                "executionPlan": None,
            },
        }
        return ensure_metrics(payload)

    status = f"已识别 {stock['code']} {stock['name']}，同花顺日K暂未取到有效数据，暂不生成评分。"
    payload = pending_payload(stock, status, quote_note=kline_result.get("reason"))
    return ensure_metrics(payload)


def search_stocks(query):
    clean = query.strip().lower()
    if not clean:
        return []
    results = [
        stock
        for stock in STOCK_MASTER
        if (
            clean in stock["code"].lower()
            or clean in stock["name"].lower()
            or clean in stock["industry"].lower()
        )
    ]
    return results[:10]


class Handler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return {}

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/evaluate":
            params = parse_qs(parsed.query)
            query = params.get("q", [""])[0]
            refresh_quote = params.get("refresh", ["0"])[0] == "1"
            refresh_fundamental = params.get("fundamental", ["0"])[0] == "1"
            refresh_kline = params.get("kline", ["0"])[0] == "1"
            self.send_json(
                evaluate_stock(
                    query,
                    refresh_quote=refresh_quote,
                    refresh_fundamental=refresh_fundamental,
                    refresh_kline=refresh_kline,
                    use_intraday=not refresh_fundamental and not refresh_kline,
                )
            )
            return
        if parsed.path == "/api/search":
            query = parse_qs(parsed.query).get("q", [""])[0]
            self.send_json({"results": search_stocks(query)})
            return
        if parsed.path == "/api/health":
            ths_status = provider_status()
            self.send_json(
                {
                    "ok": True,
                    "cacheTtlSeconds": CACHE_TTL_SECONDS,
                    "quoteCacheTtlSeconds": QUOTE_CACHE_TTL_SECONDS,
                    "minExternalIntervalSeconds": MIN_EXTERNAL_INTERVAL_SECONDS,
                    "provider": ths_status,
                    "thsEnabled": ths_status["enabled"],
                    "thsBlockedUntil": ths_status["blockedUntil"],
                    "thsFailCount": ths_status["failCount"],
                    "stockMasterSize": len(STOCK_MASTER),
                    "demoScoreSize": len(DEMO_SCORES),
                }
            )
            return
        if parsed.path == "/api/provider":
            self.send_json({"provider": provider_status(), "ths": provider_status()})
            return
        if parsed.path == "/api/tdx-bridge/status":
            self.send_json({"ok": True, **tdx_bridge_status()})
            return
        if parsed.path == "/api/refresh-progress":
            self.send_json(full_market_refresh_progress())
            return
        if parsed.path == "/api/market-sentiment":
            refresh = parse_qs(parsed.query).get("refresh", ["0"])[0] == "1"
            self.send_json(market_sentiment_status(refresh=refresh))
            return
        if parsed.path == "/api/daily-brief":
            self.send_json(build_daily_brief())
            return
        if parsed.path == "/api/watchlist":
            self.send_json(watchlist_response())
            return
        if parsed.path == "/api/sector-rankings":
            self.send_json(build_sector_rankings())
            return
        if parsed.path == "/api/industry-insight":
            self.send_json(build_industry_insight())
            return
        if parsed.path == "/api/sector-detail":
            group = parse_qs(parsed.query).get("group", [""])[0]
            self.send_json(build_sector_detail(group))
            return
        super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/watchlist":
            result = add_watchlist_item(self.read_json_body())
            self.send_json(result, status=200 if result.get("ok") else 400)
            return
        if parsed.path == "/api/watchlist/refresh-fundamentals":
            result = refresh_watchlist_fundamentals()
            self.send_json(result, status=200 if result.get("ok") else 400)
            return
        if parsed.path == "/api/home/refresh":
            result = refresh_home_data()
            self.send_json(result, status=200 if result.get("ok") else 400)
            return
        self.send_json({"ok": False, "reason": "unknown endpoint"}, status=404)

    def do_DELETE(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/watchlist":
            code = parse_qs(parsed.query).get("code", [""])[0]
            self.send_json(remove_watchlist_item(code))
            return
        self.send_json({"ok": False, "reason": "unknown endpoint"}, status=404)


if __name__ == "__main__":
    app_host = os.environ.get("APP_HOST", "127.0.0.1")
    app_port = int(os.environ.get("APP_PORT", "4173"))
    ThreadingHTTPServer.allow_reuse_address = True
    ThreadingHTTPServer.daemon_threads = True
    server = ThreadingHTTPServer((app_host, app_port), Handler)
    print(f"Serving A-share scorer at http://{app_host}:{app_port}")
    server.serve_forever()
