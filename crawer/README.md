# Zhihu Crawler

Small Python tool for exporting a Zhihu member's answers and comments to Markdown.
It uses Playwright to control Microsoft Edge with a dedicated profile, so you can
log in once and reuse the same session later.

## Files To Migrate

Copy these files into the target repository:

```text
pyproject.toml
README.md
zhihu_crawler/
scripts/validate_zhihu_comments.py
```

Do not migrate `.edge-profile/`, `.venv/`, `output*/`, `*.egg-info/`, or IDE files.

## Install

```bash
python -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/python -m playwright install chromium
```

Windows PowerShell:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m playwright install chromium
```

## Crawl

First run waits for manual Zhihu login in Edge:

```bash
.venv/bin/python -m zhihu_crawler crawl \
  --profile-url "https://www.zhihu.com/people/zhang-hao-30-99" \
  --max-answers 10 \
  --sort vote \
  --output-dir output_zhang_hao_30_99_top10
```

After login, skip the prompt:

```bash
.venv/bin/python -m zhihu_crawler crawl \
  --profile-url "https://www.zhihu.com/people/zhang-hao-30-99" \
  --max-answers 10 \
  --sort vote \
  --output-dir output_zhang_hao_30_99_top10 \
  --no-login-wait
```

By default Edge is left open. Add `--close-edge-on-exit` only when you want the
tool to close its Edge session.

## Validate Comments

```bash
.venv/bin/python scripts/validate_zhihu_comments.py output_zhang_hao_30_99_top10
```

The validator reconnects to Edge, refetches Zhihu comment pages, and compares
root comments plus nested replies against the exported Markdown.
