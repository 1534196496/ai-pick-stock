from __future__ import annotations

import argparse
from pathlib import Path
import sys

from .ai_review import append_ai_review
from .config import load_settings
from .db import Database
from .jobs import exclusive_job
from .maintenance import sync_multi_asset_data
from .pipeline import run_selection, sync_data
from .recommendations import (
    analyze_fund_batch,
    analyze_stock_batch,
    latest_complete_batch,
    sync_full_fund_universe,
    sync_full_stock_universe,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="A股数据采集与可解释选股助手")
    parser.add_argument("--config", default="config.toml", help="配置文件路径")
    sub = parser.add_subparsers(dest="command", required=True)
    sync = sub.add_parser("sync", help="拉取并保存最新行情")
    sync.add_argument("--workers", type=int, default=6)
    sub.add_parser("select", help="基于本地数据评分并生成报告")
    daily = sub.add_parser("daily", help="依次执行 sync 和 select")
    daily.add_argument("--workers", type=int, default=6)
    multiasset = sub.add_parser("multiasset", help="刷新全球行情、用户基金、美债曲线和事件缓存")
    multiasset.add_argument("--workers", type=int, default=6)
    recommendation = sub.add_parser("recommend", help="全量拉取并生成可追溯的股票/基金板块候选")
    recommendation.add_argument("--asset", choices=("stock", "fund", "all"), default="all")
    recommendation.add_argument("--analyze-only", action="store_true", help="使用最近完整快照，不重新联网拉取")
    recommendation.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()
    settings = load_settings(args.config)
    db = Database(settings.database)
    lock = settings.database.parent / ".writer.lock"
    partial = False
    with exclusive_job(db, lock, f"cli_{args.command}") as job:
        if args.command == "recommend":
            targets = ("stock", "fund") if args.asset == "all" else (args.asset,)
            for target in targets:
                try:
                    if args.analyze_only:
                        batch = latest_complete_batch(db, target)
                        if batch is None:
                            raise RuntimeError(f"没有可分析的完整 {target} 快照")
                        batch_id = str(batch.batch_id)
                    elif target == "stock":
                        synced = sync_full_stock_universe(db)
                        batch_id = synced["batch_id"]
                        if synced["status"] != "complete":
                            raise RuntimeError("股票全量快照不完整")
                    else:
                        synced = sync_full_fund_universe(db)
                        batch_id = synced["batch_id"]
                        if synced["status"] != "complete":
                            raise RuntimeError("基金全量快照不完整")
                    result = (
                        analyze_stock_batch(db, batch_id, workers=args.workers)
                        if target == "stock"
                        else analyze_fund_batch(db, batch_id, workers=args.workers)
                    )
                    job["succeeded"] += result["published"]
                    job["failed"] += len(result["failures"])
                    print(
                        f"{target}: run={result['run_id']} status={result['status']} "
                        f"sections={result['sections']} published={result['published']}"
                    )
                    if result["status"] != "complete":
                        partial = True
                except Exception as error:
                    job["failed"] += 1
                    job["message"] = f"{target}: {type(error).__name__}: {error}"
                    partial = True
                    print(job["message"], file=sys.stderr)
        if args.command in {"sync", "daily"}:
            result = sync_data(settings, args.workers)
            job["succeeded"] = result["updated"]
            job["failed"] = len(result["failures"])
            partial = bool(result["failures"])
            print(f"股票池 {result['universe']}，有新增行情 {result['updated']}，失败 {len(result['failures'])}")
            for failure in result["failures"][:20]:
                print("  -", failure)
            if partial:
                job["message"] = "部分标的同步失败；未生成候选报告"
        if args.command in {"multiasset", "daily"}:
            global_result = sync_multi_asset_data(db, args.workers)
            job["succeeded"] += global_result["succeeded"]
            job["failed"] += global_result["failed"]
            partial = partial or bool(global_result["failed"])
            print(f"全球/多资产成功 {global_result['succeeded']}，失败 {global_result['failed']}")
            for failure in global_result["failures"][:20]:
                print("  -", failure)
            if global_result["failed"]:
                job["message"] = f"多资产部分失败 {global_result['failed']} 项；未生成新的正式候选"
        if args.command in {"select", "daily"} and not partial:
            picks, report = run_selection(settings)
            job["succeeded"] = max(job["succeeded"], len(picks))
            if settings.ai_enabled:
                append_ai_review(report, settings.ai_model)
            print(picks[["rank", "code", "name", "score", "reasons"]].to_string(index=False))
            print(f"报告：{report}")
    if partial:
        print("任务为 partial：请修复失败标的后重试，计划任务将返回非零状态。", file=sys.stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
