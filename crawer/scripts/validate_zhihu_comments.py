from __future__ import annotations

import argparse
import asyncio
import json
import re
from pathlib import Path
from typing import Any

from playwright.async_api import async_playwright

from zhihu_crawler.browser import EdgeSession

ROOT_RE = re.compile(r"^\d+\. \*\*", re.MULTILINE)
REPLY_RE = re.compile(r"^  - \*\*", re.MULTILINE)


def answer_id_from_url(url: str) -> str:
    return url.rstrip("/").rsplit("/", 1)[-1]


async def fetch_json(page, url: str) -> dict[str, Any]:
    last_error = ""
    for attempt in range(5):
        try:
            return await page.evaluate(
                """
                async url => {
                  const absoluteUrl = new URL(url, location.origin).toString();
                  const res = await fetch(absoluteUrl, {credentials: 'include'});
                  if (!res.ok) throw new Error(`${res.status} ${absoluteUrl}`);
                  return await res.json();
                }
                """,
                url,
            )
        except Exception as exc:
            last_error = repr(exc)
            await asyncio.sleep(1 + attempt)
    raise RuntimeError(last_error)


async def fetch_root_comments(page, answer_id: str) -> list[dict[str, Any]]:
    comments_by_id: dict[str, dict[str, Any]] = {}
    for order_by in ["ts", "score"]:
        url = f"/api/v4/comment_v5/answers/{answer_id}/root_comment?order_by={order_by}&limit=20&offset="
        for _ in range(500):
            data = await fetch_json(page, url)
            for item in data.get("data") or []:
                item_id = str(item.get("id") or "")
                if item_id and item_id not in comments_by_id:
                    comments_by_id[item_id] = item
            paging = data.get("paging") or {}
            if paging.get("is_end"):
                break
            url = paging.get("next") or ""
            if not url:
                break
            await asyncio.sleep(0.12)
    comments = list(comments_by_id.values())
    comments.sort(key=lambda item: int(item.get("created_time") or 0), reverse=True)
    return comments


async def fetch_child_comments(page, root: dict[str, Any]) -> list[dict[str, Any]]:
    children = list(root.get("child_comments") or [])
    seen = {str(item.get("id") or "") for item in children if item.get("id")}
    expected = int(root.get("child_comment_count") or 0)
    if expected <= len(seen):
        return children

    root_id = str(root.get("id") or "")
    candidates = [
        f"/api/v4/comment_v5/comments/{root_id}/child_comment?order_by=score&limit=20&offset=",
        f"/api/v4/comment_v5/comment/{root_id}/child_comment?order_by=score&limit=20&offset=",
    ]
    for first_url in candidates:
        url = first_url
        got_response = False
        fetched = list(children)
        fetched_seen = set(seen)
        for _ in range(200):
            try:
                data = await fetch_json(page, url)
            except Exception:
                break
            got_response = True
            for item in data.get("data") or []:
                item_id = str(item.get("id") or "")
                if item_id and item_id not in fetched_seen:
                    fetched_seen.add(item_id)
                    fetched.append(item)
            paging = data.get("paging") or {}
            if paging.get("is_end"):
                break
            url = paging.get("next") or ""
            if not url:
                break
            await asyncio.sleep(0.08)
        if got_response:
            return fetched
    return children


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--profile-dir", type=Path, default=Path(".edge-profile"))
    parser.add_argument("--answer-id", action="append", default=[])
    args = parser.parse_args()

    state = json.loads((args.output_dir / "state.json").read_text(encoding="utf-8"))
    answer_ids = set(args.answer_id)

    async with EdgeSession(profile_dir=args.profile_dir, keep_open=True, slow_mo_ms=0) as session:
        page = await session.new_page()
        await page.goto("https://www.zhihu.com/", wait_until="domcontentloaded", timeout=30000)

        print("answer_id\tmd_roots\tapi_roots\tmd_replies\tapi_replies\tstatus\tfile")
        for url, rel_path in state.get("completed", {}).items():
            answer_id = answer_id_from_url(url)
            if answer_ids and answer_id not in answer_ids:
                continue
            path = Path(rel_path)
            text = path.read_text(encoding="utf-8")
            md_roots = len(ROOT_RE.findall(text))
            md_replies = len(REPLY_RE.findall(text))

            try:
                roots = await fetch_root_comments(page, answer_id)
                reply_counts = await asyncio.gather(*(fetch_child_comments(page, root) for root in roots))
                api_replies = sum(len(items) for items in reply_counts)
                api_roots = len(roots)
                status = "OK" if (md_roots == api_roots and md_replies == api_replies) else "MISMATCH"
            except Exception as exc:
                api_roots = -1
                api_replies = -1
                status = f"ERROR:{type(exc).__name__}"
            print(
                f"{answer_id}\t{md_roots}\t{api_roots}\t{md_replies}\t{api_replies}\t{status}\t{path.name}",
                flush=True,
            )


if __name__ == "__main__":
    asyncio.run(main())
