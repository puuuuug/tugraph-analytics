from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from .browser import DEFAULT_EDGE_EXECUTABLE
from .crawler import CrawlConfig, ZhihuCrawler

DEFAULT_PROFILE_URL = "https://www.zhihu.com/people/jerryma183"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="zhihu-crawler")
    subparsers = parser.add_subparsers(dest="command", required=True)

    crawl = subparsers.add_parser("crawl", help="crawl Zhihu answers")
    crawl.add_argument("--profile-url", default=DEFAULT_PROFILE_URL)
    crawl.add_argument("--max-answers", type=int, default=10)
    crawl.add_argument("--output-dir", type=Path, default=Path("output"))
    crawl.add_argument("--profile-dir", type=Path, default=Path(".edge-profile"))
    crawl.add_argument("--edge-executable", default=DEFAULT_EDGE_EXECUTABLE)
    crawl.add_argument("--state-file", type=Path, default=None)
    crawl.add_argument("--no-login-wait", action="store_true")
    crawl.add_argument("--close-edge-on-exit", action="store_true")
    crawl.add_argument(
        "--sort",
        choices=["vote", "time"],
        default="vote",
        help="answer list order; vote means Zhihu's 按赞同排序",
    )
    return parser


async def run_crawl(args: argparse.Namespace) -> None:
    config = CrawlConfig(
        profile_url=args.profile_url,
        max_answers=args.max_answers,
        output_dir=args.output_dir,
        profile_dir=args.profile_dir,
        edge_executable=args.edge_executable,
        state_file=args.state_file,
        login_wait=not args.no_login_wait,
        keep_edge_open=not args.close_edge_on_exit,
        answer_sort=args.sort,
    )
    await ZhihuCrawler(config).run()


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "crawl":
        asyncio.run(run_crawl(args))
    else:
        parser.error(f"unknown command: {args.command}")
