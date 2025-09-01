#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import os
import re
from pathlib import Path
from typing import List
from yt_dlp import YoutubeDL

DOWNLOAD_DIR = Path("downloads")
DOWNLOAD_DIR.mkdir(exist_ok=True)

BANNER = r"""
==========================================
  YouTube Downloader (MP4 / MP3 / WAV)
  - Hỗ trợ link video đơn, playlist, nhiều link
==========================================
"""

def parse_input_urls(argv: List[str]) -> List[str]:
    """
    Nhận danh sách URL từ:
      - Tham số dòng lệnh: python yt_downloader.py <url1> <url2> ...
      - Nếu không có: hỏi người dùng dán link (ngăn cách bởi khoảng trắng hoặc xuống dòng)
    """
    if len(argv) > 1:
        return argv[1:]
    print("Nhập 1 hoặc nhiều link YouTube (cách nhau bởi khoảng trắng hoặc xuống dòng).")
    print("Kết thúc bằng dòng trống:")
    buf = []
    while True:
        line = input().strip()
        if not line:
            break
        buf.extend(re.split(r"\s+", line))
    urls = [u for u in buf if u]
    if not urls:
        print("Không có URL nào. Thoát.")
        sys.exit(1)
    return urls


def choose_mode() -> str:
    """
    Hỏi người dùng chọn chế độ xuất:
      1) MP4 (video chất lượng cao nhất)
      2) MP3 (âm thanh)
      3) WAV (âm thanh)
    """
    print("\nChọn chế độ xuất:")
    print("  1) Video MP4 (chất lượng cao nhất)")
    print("  2) Âm thanh MP3")
    print("  3) Âm thanh WAV")
    while True:
        choice = input("Nhập 1 / 2 / 3: ").strip()
        if choice in {"1", "2", "3"}:
            return choice
        print("Lựa chọn không hợp lệ, hãy nhập 1, 2 hoặc 3.")


def progress_hook(d):
    if d["status"] == "downloading":
        eta = d.get("eta")
        spd = d.get("speed")
        p = d.get("_percent_str", "").strip()
        print(f"Đang tải: {p}  |  Tốc độ: {spd or '-'}  |  ETA: {eta or '-'}", end="\r", flush=True)
    elif d["status"] == "finished":
        print("\n✓ Tải xong, đang xử lý (ffmpeg)...")

def make_opts_for_mode(mode: str):
    """
    Trả về cấu hình yt-dlp theo mode.
    - MP4: gộp bestvideo+bestaudio thành .mp4 (ưu tiên H.264/AAC)
    - MP3/WAV: trích âm thanh tốt nhất rồi chuyển định dạng
    """
    common = {
        "outtmpl": str(DOWNLOAD_DIR / "%(title)s [%(id)s].%(ext)s"),
        "ignoreerrors": True,
        "noplaylist": False,            # Cho phép playlist
        "concurrent_fragment_downloads": 4,
        "retries": 10,
        "fragment_retries": 10,
        "http_chunk_size": 10485760,    # 10MB
        "progress_hooks": [progress_hook],
        "trim_file_name": 240,
        "quiet": False,
        "no_warnings": True,
    }

    if mode == "1":
        # Video MP4 chất lượng cao nhất có thể (ưu tiên mp4/h264 + m4a)
        opts = {
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
        return opts

    if mode in {"2", "3"}:
        target = "mp3" if mode == "2" else "wav"
        # Lấy bestaudio rồi chuyển codec đích
        opts = {
            **common,
            "format": "bestaudio/best",
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": target,
                    "preferredquality": "0",  # tốt nhất
                },
                {"key": "FFmpegMetadata"},
            ],
            # Đảm bảo phần mở rộng đúng
            "prefer_ffmpeg": True,
        }
        return opts

    raise ValueError("Mode không hợp lệ")


def download_all(urls: List[str], mode: str):
    ydl_opts = make_opts_for_mode(mode)
    print("\nCấu hình xuất:", "MP4" if mode == "1" else ("MP3" if mode == "2" else "WAV"))
    print(f"Thư mục lưu: {DOWNLOAD_DIR.resolve()}\n")

    with YoutubeDL(ydl_opts) as ydl:
        try:
            ydl.download(urls)
        except Exception as e:
            print(f"\n❌ Lỗi: {e}")
            sys.exit(2)

    print("\n✅ Hoàn tất.")


def main():
    print(BANNER)
    urls = parse_input_urls(sys.argv)
    mode = choose_mode()
    download_all(urls, mode)


if __name__ == "__main__":
    main()
