from __future__ import annotations

import asyncio
import html
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

from .browser import DEFAULT_EDGE_EXECUTABLE, EdgeSession
from .markdown import write_answer_markdown
from .models import Answer, Comment
from .state import CrawlState


@dataclass(frozen=True)
class CrawlConfig:
    profile_url: str
    max_answers: int
    output_dir: Path
    profile_dir: Path
    edge_executable: str = DEFAULT_EDGE_EXECUTABLE
    state_file: Path | None = None
    login_wait: bool = True
    keep_edge_open: bool = True
    answer_sort: str = "vote"

    @property
    def resolved_state_file(self) -> Path:
        return self.state_file or self.output_dir / "state.json"


@dataclass(frozen=True)
class AnswerRef:
    url: str
    answer_id: str
    question_title: str = ""
    author: str = ""
    content: str = ""
    created_or_updated: str = ""


class ZhihuCrawler:
    def __init__(self, config: CrawlConfig) -> None:
        self.config = config
        self.state = CrawlState.load(config.resolved_state_file)

    async def run(self) -> None:
        async with EdgeSession(
            profile_dir=self.config.profile_dir,
            executable_path=self.config.edge_executable,
            keep_open=self.config.keep_edge_open,
        ) as session:
            page = await session.new_page()
            await page.goto(self.config.profile_url, wait_until="domcontentloaded")
            if self.config.login_wait:
                print("Edge 已打开。若尚未登录知乎，请在浏览器中完成登录/验证，然后回到终端按 Enter。")
                await asyncio.to_thread(input)
                await page.goto(self.config.profile_url, wait_until="domcontentloaded")

            answer_refs = await self.collect_answer_refs(page)
            print(f"收集到 {len(answer_refs)} 条回答。")
            for index, answer_ref in enumerate(answer_refs, start=1):
                state_key = answer_ref.url
                if state_key in self.state.completed:
                    print(f"[{index}/{len(answer_refs)}] 已跳过: {answer_ref.url}")
                    continue
                try:
                    print(f"[{index}/{len(answer_refs)}] 抓取: {answer_ref.url}")
                    answer = await self.crawl_answer_from_list(page, answer_ref)
                    output_path = write_answer_markdown(answer, self.config.output_dir)
                    self.state.completed[state_key] = str(output_path)
                    self.state.failed.pop(state_key, None)
                    self.state.save(self.config.resolved_state_file)
                    print(f"  已写入: {output_path}")
                except Exception as exc:
                    self.state.failed[state_key] = repr(exc)
                    self.state.save(self.config.resolved_state_file)
                    print(f"  失败: {exc!r}")

    async def collect_answer_refs(self, page: Page) -> list[AnswerRef]:
        await self._goto_answers_tab(page)
        return (await self._fetch_answer_refs_via_api(page))[: self.config.max_answers]

    async def crawl_answer_from_list(self, page: Page, answer_ref: AnswerRef) -> Answer:
        await self._goto_answers_tab(page)
        question_title = answer_ref.question_title
        author = answer_ref.author
        created_or_updated = answer_ref.created_or_updated
        content = answer_ref.content
        if not content:
            detail = await self._fetch_answer_detail_via_api(page, answer_ref)
            question_title = question_title or detail.question_title
            author = author or detail.author
            created_or_updated = created_or_updated or detail.created_or_updated
            content = detail.content
        content = self._strip_answer_ads(content)
        comments = await self._fetch_comments_via_api(page, answer_ref.answer_id)

        return Answer(
            url=answer_ref.url,
            answer_id=answer_ref.answer_id,
            question_title=question_title or "知乎回答",
            author=author,
            created_or_updated=created_or_updated,
            content=content,
            comments=comments,
        )

    async def _fetch_answer_detail_via_api(self, page: Page, answer_ref: AnswerRef) -> AnswerRef:
        raw = await page.evaluate(
            """
            async answerId => {
              const include = [
                'content',
                'created_time',
                'updated_time',
                'author',
                'question'
              ].join(',');
              const res = await fetch(`/api/v4/answers/${answerId}?include=${encodeURIComponent(include)}`, {credentials: 'include'});
              if (!res.ok) return null;
              return await res.json();
            }
            """,
            answer_ref.answer_id,
        )
        if not raw:
            return answer_ref
        question = raw.get("question") or {}
        updated = raw.get("updated_time") or raw.get("created_time")
        return AnswerRef(
            url=answer_ref.url,
            answer_id=answer_ref.answer_id,
            question_title=str(question.get("title") or answer_ref.question_title),
            author=str((raw.get("author") or {}).get("name") or answer_ref.author),
            content=self._strip_answer_ads(self._html_to_text(str(raw.get("content") or answer_ref.content or ""))),
            created_or_updated=self._format_timestamp(updated) or answer_ref.created_or_updated,
        )

    async def _fetch_answer_refs_via_api(self, page: Page) -> list[AnswerRef]:
        sort_by = "voteups" if self.config.answer_sort == "vote" else "created"
        raw_answers = await page.evaluate(
            """
            async ({profileUrl, maxAnswers, sortBy}) => {
              const token = profileUrl.replace(/\\/$/, '').split('/').pop();
              const include = [
                'data[*].comment_count',
                'data[*].voteup_count',
                'data[*].content',
                'data[*].created_time',
                'data[*].updated_time',
                'data[*].author',
                'data[*].question'
              ].join(',');
              const answers = [];
              let offset = 0;
              for (let pageNo = 0; answers.length < maxAnswers && pageNo < 20; pageNo += 1) {
                const url = `/api/v4/members/${token}/answers?include=${encodeURIComponent(include)}&offset=${offset}&limit=20&sort_by=${sortBy}`;
                const res = await fetch(url, {credentials: 'include'});
                if (!res.ok) throw new Error(`${res.status} ${url}`);
                const json = await res.json();
                answers.push(...(json.data || []));
                if (!json.paging || json.paging.is_end) break;
                offset += 20;
              }
              return answers.slice(0, maxAnswers);
            }
            """,
            {
                "profileUrl": self.config.profile_url,
                "maxAnswers": self.config.max_answers,
                "sortBy": sort_by,
            },
        )
        refs: list[AnswerRef] = []
        for raw in raw_answers:
            answer_id = str(raw.get("id") or "")
            question = raw.get("question") or {}
            question_id = str(question.get("id") or "")
            if not answer_id or not question_id:
                continue
            updated = raw.get("updated_time") or raw.get("created_time")
            refs.append(
                AnswerRef(
                    url=f"https://www.zhihu.com/question/{question_id}/answer/{answer_id}",
                    answer_id=answer_id,
                    question_title=str(question.get("title") or "知乎回答"),
                    author=str((raw.get("author") or {}).get("name") or ""),
                    content=self._strip_answer_ads(self._html_to_text(str(raw.get("content") or ""))),
                    created_or_updated=self._format_timestamp(updated),
                )
            )
        return refs

    async def _goto_answers_tab(self, page: Page) -> None:
        if "/answers" not in page.url:
            answers_url = self.config.profile_url.rstrip("/") + "/answers"
            await page.goto(answers_url, wait_until="domcontentloaded")
            await self._settle(page)
        try:
            await page.wait_for_selector(".AnswerItem, [class*='AnswerItem']", timeout=12000)
        except PlaywrightTimeoutError:
            await page.reload(wait_until="domcontentloaded")
            await self._settle(page)
            try:
                await page.wait_for_selector(".AnswerItem, [class*='AnswerItem']", timeout=12000)
            except PlaywrightTimeoutError:
                pass

    async def _fetch_comments_via_api(self, page: Page, answer_id: str) -> list[Comment]:
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                raw_comments = await asyncio.wait_for(
                    page.evaluate(
                        """
                        async answerId => {
                          const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
                          const fetchJson = async url => {
                            let lastError = '';
                            for (let attempt = 0; attempt < 5; attempt += 1) {
                              try {
                                const absoluteUrl = new URL(url, location.origin).toString();
                                const res = await fetch(absoluteUrl, {credentials: 'include'});
                                if (!res.ok) throw new Error(`${res.status} ${absoluteUrl}`);
                                return await res.json();
                              } catch (error) {
                                lastError = String(error && error.message || error);
                                await sleep(700 + attempt * 700);
                              }
                            }
                            throw new Error(lastError);
                          };
                          const childUrls = rootId => [
                            `/api/v4/comment_v5/comments/${rootId}/child_comment?order_by=score&limit=20&offset=`,
                            `/api/v4/comment_v5/comment/${rootId}/child_comment?order_by=score&limit=20&offset=`,
                          ];
                          const fetchChildren = async root => {
                            const children = [...(root.child_comments || [])];
                            const seen = new Set(children.map(child => String(child.id)));
                            if ((root.child_comment_count || 0) <= children.length) return children;
                            for (const firstUrl of childUrls(root.id)) {
                              let url = firstUrl;
                              let ok = false;
                              for (let pageNo = 0; url && pageNo < 100; pageNo += 1) {
                                try {
                                  const json = await fetchJson(url);
                                  ok = true;
                                  for (const child of json.data || []) {
                                    const id = String(child.id || '');
                                    if (!seen.has(id)) {
                                      seen.add(id);
                                      children.push(child);
                                    }
                                  }
                                  url = json.paging && !json.paging.is_end ? json.paging.next : '';
                                  await sleep(250);
                                } catch {
                                  break;
                                }
                              }
                              if (ok) break;
                            }
                            return children;
                          };

                          const commentsById = new Map();
                          for (const orderBy of ['ts', 'score']) {
                            let url = `/api/v4/comment_v5/answers/${answerId}/root_comment?order_by=${orderBy}&limit=20&offset=`;
                            for (let pageNo = 0; url && pageNo < 200; pageNo += 1) {
                              const json = await fetchJson(url);
                              for (const root of json.data || []) {
                                if (!commentsById.has(String(root.id))) {
                                  root.child_comments = await fetchChildren(root);
                                  commentsById.set(String(root.id), root);
                                }
                              }
                              url = json.paging && !json.paging.is_end ? json.paging.next : '';
                              await sleep(350);
                            }
                          }
                          return [...commentsById.values()].sort((a, b) => (b.created_time || 0) - (a.created_time || 0));
                        }
                        """,
                        answer_id,
                    ),
                    timeout=240,
                )
                return [self._api_comment_to_model(raw) for raw in raw_comments]
            except (asyncio.TimeoutError, Exception) as exc:
                last_error = exc
                await page.wait_for_timeout(1500 + attempt * 1500)
        print(f"  评论接口失败，跳过评论: {answer_id} {last_error!r}")
        return []

    def _api_comment_to_model(self, raw: dict, parent_author: str = "") -> Comment:
        reply_to = ""
        reply_author = raw.get("reply_to_author") or raw.get("reply_author") or {}
        if isinstance(reply_author, dict):
            reply_to = str(reply_author.get("name") or "")
        reply_parent = str(raw.get("reply_comment_id") or "")
        reply_root = str(raw.get("reply_root_comment_id") or "")
        if not reply_to and reply_parent and reply_parent != "0":
            reply_to = parent_author if reply_parent == reply_root and parent_author else "上级评论"
        author = str((raw.get("author") or {}).get("name", ""))
        return Comment(
            author=author,
            text=self._html_to_text(str(raw.get("content") or "")),
            time=self._format_timestamp(raw.get("created_time")),
            vote_count=str(raw.get("like_count") or ""),
            reply_to=reply_to,
            comment_id=str(raw.get("id") or ""),
            replies=[
                self._api_comment_to_model(child, parent_author=author)
                for child in raw.get("child_comments") or []
            ],
        )

    async def _settle(self, page: Page) -> None:
        try:
            await page.wait_for_load_state("networkidle", timeout=8000)
        except PlaywrightTimeoutError:
            pass
        await page.wait_for_timeout(1200)

    def _format_timestamp(self, value: object) -> str:
        try:
            return datetime.fromtimestamp(int(value)).strftime("%Y-%m-%d %H:%M")
        except Exception:
            return ""

    def _html_to_text(self, value: str) -> str:
        value = re.sub(r"(?i)<br\\s*/?>", "\n", value)
        value = re.sub(r"(?i)</p\\s*>", "\n", value)
        value = re.sub(r"(?i)<p[^>]*>", "", value)
        value = re.sub(r"<[^>]+>", "", value)
        return self._clean_text(html.unescape(value))

    def _strip_answer_ads(self, value: str) -> str:
        lines = value.splitlines()
        for index, line in enumerate(lines):
            if line.strip() == "广告":
                return "\n".join(lines[:index]).rstrip()
        return value

    def _clean_text(self, value: str) -> str:
        return re.sub(r"\n{3,}", "\n\n", value.replace("\u200b", "").strip())
