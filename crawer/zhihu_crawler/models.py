from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Comment:
    author: str
    text: str
    time: str = ""
    vote_count: str = ""
    reply_to: str = ""
    comment_id: str = ""
    replies: list["Comment"] = field(default_factory=list)


@dataclass(frozen=True)
class Answer:
    url: str
    answer_id: str
    question_title: str
    author: str
    content: str
    created_or_updated: str = ""
    comments: list[Comment] = field(default_factory=list)
