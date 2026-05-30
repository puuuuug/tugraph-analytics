from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from zhihu_crawler.browser import EdgeSession


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("member")
    parser.add_argument("--profile-dir", type=Path, default=Path(".edge-profile"))
    parser.add_argument("--sort", choices=["voteups", "created"], default="voteups")
    args = parser.parse_args()

    async with EdgeSession(args.profile_dir, keep_open=True, slow_mo_ms=0) as session:
        page = await session.new_page()
        await page.goto(f"https://www.zhihu.com/people/{args.member}/answers", wait_until="domcontentloaded")
        stats = await page.evaluate(
            """
            async ({member, sort}) => {
              const include = 'data[*].question';
              const ids = [];
              let offset = 0;
              let pages = 0;
              while (pages < 200) {
                const params = new URLSearchParams({
                  include,
                  offset: String(offset),
                  limit: '20',
                  sort_by: sort,
                });
                const res = await fetch(`/api/v4/members/${member}/answers?${params}`, {credentials: 'include'});
                if (!res.ok) throw new Error(`${res.status} ${res.url}`);
                const json = await res.json();
                ids.push(...(json.data || []).map(item => String(item.id || '')));
                pages += 1;
                if (!json.paging || json.paging.is_end) break;
                offset += 20;
              }
              const unique = [...new Set(ids)];
              return {
                pages,
                totalRows: ids.length,
                uniqueAnswers: unique.length,
                duplicateRows: ids.length - unique.length,
                lastIds: ids.slice(-5),
              };
            }
            """,
            {"member": args.member, "sort": args.sort},
        )
        print(stats)


if __name__ == "__main__":
    asyncio.run(main())
