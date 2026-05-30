from __future__ import annotations

import asyncio
import json
import os
import platform
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

from playwright.async_api import Browser, BrowserContext, Page, async_playwright


def default_edge_executable() -> str:
    system = platform.system()
    if system == "Darwin":
        return "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"
    if system == "Windows":
        candidates = [
            os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
            os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
            os.path.expandvars(r"%LocalAppData%\Microsoft\Edge\Application\msedge.exe"),
        ]
        return next((path for path in candidates if os.path.exists(path)), "msedge.exe")
    return "microsoft-edge"


DEFAULT_EDGE_EXECUTABLE = default_edge_executable()


class EdgeSession:
    def __init__(
        self,
        profile_dir: Path,
        executable_path: str = DEFAULT_EDGE_EXECUTABLE,
        headless: bool = False,
        slow_mo_ms: int = 80,
        keep_open: bool = True,
    ) -> None:
        self.profile_dir = profile_dir
        self.executable_path = executable_path
        self.headless = headless
        self.slow_mo_ms = slow_mo_ms
        self.keep_open = keep_open
        self._playwright = None
        self.browser: Browser | None = None
        self.context: BrowserContext | None = None
        self._process: subprocess.Popen | None = None
        self._debug_ports = [9222, 9333, 9444, 9555]
        self._debug_port = self._debug_ports[0]

    async def __aenter__(self) -> "EdgeSession":
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self._playwright = await async_playwright().start()
        last_error: Exception | None = None
        for port in self._debug_ports:
            self._debug_port = port
            try:
                await self._ensure_edge_process()
                ws_url = await self._cdp_websocket_url()
                self.browser = await self._playwright.chromium.connect_over_cdp(
                    ws_url,
                    slow_mo=self.slow_mo_ms,
                    timeout=5000,
                )
                break
            except Exception as exc:
                last_error = exc
                continue
        if self.browser is None:
            raise RuntimeError(f"无法连接 Edge CDP: {last_error!r}")
        self.context = self.browser.contexts[0] if self.browser.contexts else await self.browser.new_context()
        try:
            await self.context.set_viewport_size({"width": 1440, "height": 1000})
        except Exception:
            pass
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self.browser and not self.keep_open:
            await self.browser.close()
            if self._process and self._process.poll() is None:
                self._process.terminate()
        if self._playwright:
            await self._playwright.stop()

    async def new_page(self) -> Page:
        if self.context is None:
            raise RuntimeError("EdgeSession has not been started")
        page = self.context.pages[0] if self.context.pages else await self.context.new_page()
        for extra_page in self.context.pages[1:]:
            await extra_page.close()
        return page

    async def _ensure_edge_process(self) -> None:
        if await self._cdp_ready():
            return
        args = [
            self.executable_path,
            f"--remote-debugging-port={self._debug_port}",
            f"--user-data-dir={self.profile_dir.resolve()}",
            "--disable-blink-features=AutomationControlled",
            "--no-first-run",
            "--no-default-browser-check",
            "about:blank",
        ]
        self._process = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        for _ in range(50):
            if await self._cdp_ready():
                return
            await asyncio.sleep(0.2)
        raise RuntimeError(f"Edge CDP 端口未就绪: {self._debug_port}")

    async def _cdp_ready(self) -> bool:
        def check() -> bool:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{self._debug_port}/json/version", timeout=0.5) as res:
                    return res.status == 200
            except (OSError, urllib.error.URLError):
                return False

        return await asyncio.to_thread(check)

    async def _cdp_websocket_url(self) -> str:
        def read_url() -> str:
            with urllib.request.urlopen(f"http://127.0.0.1:{self._debug_port}/json/version", timeout=1) as res:
                data = res.read().decode("utf-8")
            match = json.loads(data).get("webSocketDebuggerUrl")
            if not match:
                raise RuntimeError("CDP webSocketDebuggerUrl missing")
            return str(match)

        return await asyncio.to_thread(read_url)
