#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import threading
import queue
import time
from pathlib import Path
from typing import List, Optional
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from yt_dlp import YoutubeDL

APP_TITLE = "YouTube Downloader — GUI"
DEFAULT_DOWNLOAD_DIR = Path("downloads")
DEFAULT_LINK_FILE = Path("link.txt")

# ---------------------- Logic yt-dlp ----------------------

def make_opts_for_mode(mode: str, outdir: Path, progress_hook):
    """
    mode: 'MP4' | 'MP3' | 'WAV'
    """
    common = {
        "outtmpl": str(outdir / "%(title)s [%(id)s].%(ext)s"),
        "ignoreerrors": True,
        "noplaylist": False,
        "concurrent_fragment_downloads": 4,
        "retries": 10,
        "fragment_retries": 10,
        "http_chunk_size": 10 * 1024 * 1024,
        "progress_hooks": [progress_hook],
        "trim_file_name": 240,
        "quiet": True,         # im lặng, chỉ dùng hook để log
        "no_warnings": True,
    }

    if mode == "MP4":
        return {
            **common,
            "format": (
                "bestvideo[ext=mp4][vcodec*=avc]/bestvideo[vcodec*=avc]+bestaudio[ext=m4a]/"
                "best[ext=mp4]/best"
            ),
            "merge_output_format": "mp4",
            "postprocessors": [
                {"key": "FFmpegVideoConvertor", "preferedformat": "mp4"},
                {"key": "FFmpegMetadata"},
            ],
        }

    target = "mp3" if mode == "MP3" else "wav"
    return {
        **common,
        "format": "bestaudio/best",
        "postprocessors": [
            {"key": "FFmpegExtractAudio", "preferredcodec": target, "preferredquality": "0"},
            {"key": "FFmpegMetadata"},
        ],
        "prefer_ffmpeg": True,
    }


# ---------------------- GUI App ----------------------

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("820x640")
        self.minsize(760, 560)

        self.urls_text = tk.Text(self, height=10, wrap="word")
        self.mode_var = tk.StringVar(value="MP4")
        self.dir_var = tk.StringVar(value=str((Path.cwd() / DEFAULT_DOWNLOAD_DIR).resolve()))
        self.overall_var = tk.DoubleVar(value=0.0)
        self.current_var = tk.DoubleVar(value=0.0)
        self.status_var = tk.StringVar(value="Sẵn sàng.")
        self.queue = queue.Queue()
        self.worker: Optional[threading.Thread] = None
        self.stop_flag = threading.Event()

        self._build_ui()

    # --------- UI layout ----------
    def _build_ui(self):
        pad = {"padx": 10, "pady": 8}

        frm_top = ttk.Frame(self)
        frm_top.pack(fill="x", **pad)

        ttk.Label(frm_top, text="Đầu ra:").grid(row=0, column=0, sticky="w")
        fmt = ttk.Combobox(frm_top, textvariable=self.mode_var, values=["MP4", "MP3", "WAV"], state="readonly", width=8)
        fmt.grid(row=0, column=1, sticky="w", padx=(6, 18))

        ttk.Label(frm_top, text="Thư mục lưu:").grid(row=0, column=2, sticky="w")
        ent_dir = ttk.Entry(frm_top, textvariable=self.dir_var, width=50)
        ent_dir.grid(row=0, column=3, sticky="ew", padx=(6, 6))
        btn_browse = ttk.Button(frm_top, text="Chọn…", command=self.choose_dir)
        btn_browse.grid(row=0, column=4, sticky="w")

        frm_top.columnconfigure(3, weight=1)

        frm_mid = ttk.Frame(self)
        frm_mid.pack(fill="both", expand=True, **pad)

        ttk.Label(frm_mid, text="Danh sách link YouTube (mỗi dòng 1 link):").pack(anchor="w")
        self.urls_text.pack(in_=frm_mid, fill="both", expand=True, pady=(6, 6))

        frm_mid_btns = ttk.Frame(frm_mid)
        frm_mid_btns.pack(fill="x")
        ttk.Button(frm_mid_btns, text="Load từ link.txt", command=self.load_from_file).pack(side="left")
        ttk.Button(frm_mid_btns, text="Lưu ra link.txt", command=self.save_to_file).pack(side="left", padx=(8, 0))
        ttk.Button(frm_mid_btns, text="Dán từ Clipboard", command=self.paste_clipboard).pack(side="left", padx=(8, 0))
        ttk.Button(frm_mid_btns, text="Xoá", command=lambda: self.urls_text.delete("1.0", "end")).pack(side="left", padx=(8, 0))

        sep = ttk.Separator(self)
        sep.pack(fill="x", padx=10, pady=6)

        frm_prog = ttk.Frame(self)
        frm_prog.pack(fill="x", **pad)

        ttk.Label(frm_prog, text="Tiến độ video hiện tại:").grid(row=0, column=0, sticky="w")
        pb1 = ttk.Progressbar(frm_prog, variable=self.current_var, maximum=100)
        pb1.grid(row=0, column=1, sticky="ew", padx=(8, 0))

        ttk.Label(frm_prog, text="Tiến độ tổng:").grid(row=1, column=0, sticky="w", pady=(6, 0))
        pb2 = ttk.Progressbar(frm_prog, variable=self.overall_var, maximum=100)
        pb2.grid(row=1, column=1, sticky="ew", padx=(8, 0), pady=(6, 0))

        frm_prog.columnconfigure(1, weight=1)

        frm_actions = ttk.Frame(self)
        frm_actions.pack(fill="x", **pad)
        self.btn_start = ttk.Button(frm_actions, text="Bắt đầu tải", command=self.start_downloads)
        self.btn_start.pack(side="left")
        self.btn_stop = ttk.Button(frm_actions, text="Dừng", command=self.stop_downloads, state="disabled")
        self.btn_stop.pack(side="left", padx=(8, 0))

        self.status_lbl = ttk.Label(self, textvariable=self.status_var, anchor="w")
        self.status_lbl.pack(fill="x", padx=12, pady=(0, 10))

        ttk.Label(self, text="Nhật ký:").pack(anchor="w", padx=10)
        self.log = tk.Text(self, height=10, wrap="word", state="disabled")
        self.log.pack(fill="both", expand=False, padx=10, pady=(6, 12))

        self.after(100, self._poll_queue)

    # --------- UI handlers ----------
    def choose_dir(self):
        folder = filedialog.askdirectory(initialdir=self.dir_var.get() or str(Path.cwd()))
        if folder:
            self.dir_var.set(folder)

    def load_from_file(self):
        if DEFAULT_LINK_FILE.exists():
            content = DEFAULT_LINK_FILE.read_text(encoding="utf-8").strip()
            if content:
                self.urls_text.delete("1.0", "end")
                self.urls_text.insert("1.0", content)
                self._log(f"Đã nạp {DEFAULT_LINK_FILE} ({len(content.splitlines())} dòng).")
            else:
                self._log("link.txt rỗng.")
        else:
            self._log("Chưa có link.txt trong thư mục ứng dụng.")

    def save_to_file(self):
        text = self.urls_text.get("1.0", "end").strip()
        DEFAULT_LINK_FILE.write_text(text, encoding="utf-8")
        self._log(f"Đã lưu danh sách link vào {DEFAULT_LINK_FILE}.")

    def paste_clipboard(self):
        try:
            data = self.clipboard_get()
            if data:
                cur = self.urls_text.get("1.0", "end").strip()
                joiner = "\n" if cur else ""
                self.urls_text.insert("end", joiner + data.strip() + "\n")
        except tk.TclError:
            pass

    # --------- Download orchestration ----------
    def start_downloads(self):
        urls = self._collect_urls()
        if not urls:
            messagebox.showwarning("Thiếu link", "Hãy nhập ít nhất một link YouTube hoặc dùng Load từ link.txt.")
            return

        outdir = Path(self.dir_var.get()).expanduser()
        outdir.mkdir(parents=True, exist_ok=True)

        mode = self.mode_var.get()
        self._log(f"▶ Bắt đầu: {len(urls)} link | Chế độ: {mode} | Lưu vào: {outdir}")
        self.status_var.set("Đang tải…")
        self.current_var.set(0)
        self.overall_var.set(0)
        self.stop_flag.clear()
        self.btn_start.config(state="disabled")
        self.btn_stop.config(state="normal")

        self.worker = threading.Thread(
            target=self._worker_download, args=(urls, mode, outdir), daemon=True
        )
        self.worker.start()

    def stop_downloads(self):
        self.stop_flag.set()
        self._log("⏹ Yêu cầu dừng tác vụ…")

    def _worker_download(self, urls: List[str], mode: str, outdir: Path):
        total = len(urls)
        done = 0

        def hook(d):
            if d["status"] == "downloading":
                pstr = d.get("_percent_str", "").strip().replace("%", "")
                try:
                    pct = float(pstr)
                except Exception:
                    pct = 0.0
                self.queue.put(("progress_current", pct))
            elif d["status"] == "finished":
                self.queue.put(("log", "✓ Tải xong, đang xử lý (ffmpeg)…"))

        ydl_opts = make_opts_for_mode(mode, outdir, hook)

        for url in urls:
            if self.stop_flag.is_set():
                self.queue.put(("log", "⏹ Đã dừng theo yêu cầu."))
                break

            self.queue.put(("log", f"— Bắt đầu: {url}"))
            self.queue.put(("progress_current", 0.0))

            try:
                with YoutubeDL(ydl_opts) as ydl:
                    ydl.download([url])
                self.queue.put(("log", "✔ Hoàn tất video/playlist này."))
            except Exception as e:
                self.queue.put(("log", f"❌ Lỗi: {e}"))

            done += 1
            overall = round(done * 100.0 / total, 2)
            self.queue.put(("progress_overall", overall))

        self.queue.put(("done", None))

    def _collect_urls(self) -> List[str]:
        text = self.urls_text.get("1.0", "end").strip()
        urls = [ln.strip() for ln in text.splitlines() if ln.strip()]
        return urls

    # --------- Messaging / log ----------
    def _poll_queue(self):
        try:
            while True:
                msg, payload = self.queue.get_nowait()
                if msg == "progress_current":
                    self.current_var.set(float(payload))
                elif msg == "progress_overall":
                    self.overall_var.set(float(payload))
                elif msg == "log":
                    self._log(payload)
                elif msg == "done":
                    self.btn_start.config(state="normal")
                    self.btn_stop.config(state="disabled")
                    self.status_var.set("Hoàn tất." if not self.stop_flag.is_set() else "Đã dừng.")
        except queue.Empty:
            pass
        self.after(100, self._poll_queue)

    def _log(self, text: str):
        self.log.configure(state="normal")
        self.log.insert("end", text.strip() + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")


if __name__ == "__main__":
    DEFAULT_DOWNLOAD_DIR.mkdir(exist_ok=True)
    app = App()
    app.mainloop()
