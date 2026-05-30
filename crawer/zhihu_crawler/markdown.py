from __future__ import annotations

import re
from pathlib import Path

from .models import Answer, Comment

_UNSAFE_FILENAME = re.compile(r'[\\/:*?"<>|\s]+')


def slugify(value: str, fallback: str = "answer") -> str:
    normalized = _UNSAFE_FILENAME.sub("-", value.strip()).strip("-")
    normalized = re.sub(r"-{2,}", "-", normalized)
    return normalized[:90] or fallback


def answer_filename(answer: Answer) -> str:
    title = slugify(answer.question_title, "zhihu-answer")
    answer_id = slugify(answer.answer_id or "unknown")
    return f"{title}-{answer_id}.md"


def write_answer_markdown(answer: Answer, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / answer_filename(answer)
    path.write_text(render_answer(answer), encoding="utf-8")
    return path


def render_answer(answer: Answer) -> str:
    lines: list[str] = [
        f"# {answer.question_title or '知乎回答'}",
        "",
        f"- 回答链接: {answer.url}",
        f"- 回答 ID: {answer.answer_id or '未知'}",
        f"- 作者: {answer.author or '未知'}",
    ]
    if answer.created_or_updated:
        lines.append(f"- 时间: {answer.created_or_updated}")

    lines.extend(["", "## 回答正文", "", answer.content.strip() or "_未抓取到正文_", ""])
    lines.extend(["## 评论", ""])

    if not answer.comments:
        lines.append("_未抓取到评论_")
    else:
        for index, comment in enumerate(answer.comments, start=1):
            lines.extend(render_comment(comment, index=index, depth=0))

    lines.append("")
    return "\n".join(lines)


def render_comment(comment: Comment, index: int, depth: int) -> list[str]:
    indent = "  " * depth
    prefix = f"{index}." if depth == 0 else "-"
    vote_text = f"{comment.vote_count} 赞" if comment.vote_count else ""
    reply_text = f"回复 @{comment.reply_to}" if comment.reply_to else ""
    meta = " / ".join(part for part in [comment.author, reply_text, comment.time, vote_text] if part)
    header = f"{indent}{prefix} **{meta or '匿名用户'}**"
    lines = [header, f"{indent}   {comment.text.strip() or '_空评论_'}", ""]
    for reply_index, reply in enumerate(comment.replies, start=1):
        lines.extend(render_comment(reply, index=reply_index, depth=depth + 1))
    return lines
