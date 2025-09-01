#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#thêm chức năng giữ âm thanh gốc

import sys
import os
import re
from pathlib import Path
from typing import List, Optional
from yt_dlp import YoutubeDL

DOWNLOAD_DIR = Path("downloads")
DOWNLOAD_DIR.mkdir(exist_ok=True)
LINK_FILE = Path("link.txt")
DEFAULT_COOKIES_CANDIDATES = [
    Path("cookies.txt"),          # ưu tiên cùng thư mục script
    Path.home() / "cookies.txt",  # fallback thư mục home
]

BANNER = r"""
==========================================
  YouTube Downloader (MP4 / MP3 / WAV)
  - Hỗ trợ video đơn, playlist, nhiều link
  - Đọc link từ link.txt
  - Hỗ trợ cookies (Netscape) để vượt giới hạn
==========================================
"""

HELP = f"""\
Cách dùng:
  python {Path(__file__).name} [--cookies PATH] [URL1 URL2 ...]

Ưu tiên lấy URL:
  1) Tham số dòng lệnh (URL1 URL2 ...)
  2) Nếu có file link.txt -> đọc từ đó (mỗi dòng 1 URL)
  3) Nếu không có -> bạn dán thủ công trong terminal

Cookies (tùy chọn, định dạng Netscape):
  - Tự động tìm {DEFAULT_COOKIES_CANDIDATES[0]} hoặc {DEFAULT_COOKIES_CANDIDATES[1]}
  - Hoặc chỉ định: --cookies path/to/cookies.txt
  - Hoặc set biến môi trường: YT_COOKIES=path/to/cookies.txt
"""

def parse_args(argv: List[str]):
    """Trả về (cookies_path, urls_list)"""
    cookies_path: Optional[str] = None
    urls: List[str] = []

    i = 1
    while i < len(argv):
        a = argv[i]
        if a in ("-h", "--help"):
            print(BANNER)
            print(HELP)
            sys.exit(0)
        if a == "--cookies":
            if i + 1 >= len(argv):
                print("Thiếu đường dẫn sau --cookies")
                sys.exit(1)
            cookies_path = argv[i + 1]
            i += 2
            continue
        urls.append(a)
        i += 1

    return cookies_path, urls


def detect_cookies_path(cli_path: Optional[str]) -> Optional[str]:
    """Ưu tiên: CLI --cookies > ENV YT_COOKIES > file mặc định."""
    if cli_path:
        p = Path(cli_path)
        return str(p) if p.exists() else None
    env = os.getenv("YT_COOKIES")
    if env:
        p = Path(env)
        if p.exists():
            return str(p)
    for cand in DEFAULT_COOKIES_CANDIDATES:
        if cand.exists():
            return str(cand)
    return None


def parse_input_urls(cli_urls: List[str]) -> List[str]:
    """
    Lấy URL theo thứ tự ưu tiên:
    1) Từ tham số dòng lệnh
    2) Từ link.txt (nếu có)
    3) Nhập thủ công
    """
    if cli_urls:
        return cli_urls

    if LINK_FILE.exists():
        print(f"Đọc danh sách link từ {LINK_FILE} ...")
        lines = LINK_FILE.read_text(encoding="utf-8").splitlines()
        urls = [ln.strip() for ln in lines if ln.strip()]
        if urls:
            return urls

    print("Nhập 1 hoặc nhiều link YouTube (cách nhau bởi khoảng trắng hoặc xuống dòng).")
    print("Kết thúc bằng dòng trống:")
    buf = []
    while True:
        try:
            line = input().strip()
        except EOFError:
            break
        if not line:
            break
        buf.extend(re.split(r"\s+", line))
    urls = [u for u in buf if u]
    if not urls:
        print("Không có URL nào. Thoát.")
        sys.exit(1)
    return urls


def choose_mode() -> str:
    print("\nChọn chế độ xuất:")
    print("  1) Video MP4 (chất lượng cao nhất)")
    print("  2) Âm thanh MP3 (convert)")
    print("  3) Âm thanh WAV (convert)")
    print("  4) Âm thanh gốc (không convert)")
    while True:
        choice = input("Nhập 1 / 2 / 3 / 4: ").strip()
        if choice in {"1", "2", "3", "4"}:
            return choice
        print("Lựa chọn không hợp lệ, hãy nhập 1, 2 hoặc 3, 4")

def danh_so() -> int():
    print("\nChọn định dạng đánh số thứ tự:")
    print("01, 02, ... Nhập 2")
    print("001, 002, ... Nhập 3")
    print("0001, 0002, ... Nhập 4")
    while True:
        choice = input("Hãy nhập kiểu đánh số 1,2,3..").strip()
        if choice in {"1", "2", "3", "4", "5"}:
            return int(choice)   # ép chuỗi thành số nguyên
        print("Lựa chọn không hợp lệ, hãy nhập 1, 2, 3, 4 hoặc 5")


def progress_hook(d):
    if d.get("status") == "downloading":
        eta = d.get("eta")
        spd = d.get("speed")
        p = d.get("_percent_str", "").strip()
        print(f"Đang tải: {p:<6} | Tốc độ: {spd or '-':<10} | ETA: {eta or '-'}", end="\r", flush=True)
    elif d.get("status") == "finished":
        print("\n✓ Tải xong, đang xử lý (ffmpeg)...")


def make_opts_for_mode(mode: str, cookies_path: Optional[str], style):
    """
    Thêm cookies nếu có (cookiefile phải là Netscape format).
    """
    common = {
        "outtmpl": str(DOWNLOAD_DIR / "%(autonumber)s - %(title)s.%(ext)s"),
        "autonumber_size": int(style),
        "ignoreerrors": True,
        "noplaylist": False,
        "concurrent_fragment_downloads": 4,
        "retries": 10,
        "fragment_retries": 10,
        "http_chunk_size": 10 * 1024 * 1024,  # 10MB
        "progress_hooks": [progress_hook],
        "trim_file_name": 240,
        "quiet": False,
        "no_warnings": True,
    }
    if cookies_path:
        common["cookiefile"] = cookies_path

    if mode == "1":
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

    if mode == "2":
        return {
            **common,
            "format": "bestaudio/best",
            "postprocessors": [
                {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "0"},
                {"key": "FFmpegMetadata"},
            ],
            "prefer_ffmpeg": True,
        }

    if mode == "3":
        return {
            **common,
            "format": "bestaudio/best",
            "postprocessors": [
                {"key": "FFmpegExtractAudio", "preferredcodec": "wav", "preferredquality": "0"},
                {"key": "FFmpegMetadata"},
            ],
            "prefer_ffmpeg": True,
        }

    if mode == "4":
        # Âm thanh gốc, không convert
        return {
            **common,
            "format": "bestaudio[ext=m4a]/bestaudio/best",
        }
    


def download_all(urls: List[str], mode: str, cookies_path: Optional[str], style):
    ydl_opts = make_opts_for_mode(mode, cookies_path, style)

    kind_map = {
    "1": "MP4",
    "2": "MP3",
    "3": "WAV",
    "4": "M4A",
    }
    kind = kind_map.get(mode, "Unknown")
    print("\n======== THÔNG TIN TÁC VỤ ========")
    print("Đầu ra    :", kind)
    print("Thư mục   :", DOWNLOAD_DIR.resolve())
    if cookies_path:
        print("Cookies   :", cookies_path)
    else:
        print("Cookies   : (không dùng)")
    print("Số link   :", len(urls))
    print("===================================\n")

    with YoutubeDL(ydl_opts) as ydl:
        try:
            ydl.download(urls)
        except Exception as e:
            print(f"\n❌ Lỗi: {e}")
            sys.exit(2)

    print("\n✅ Hoàn tất.")


def main():
    print(BANNER)
    cookies_cli, cli_urls = parse_args(sys.argv)
    urls = parse_input_urls(cli_urls)
    mode = choose_mode()
    style = danh_so()
    cookies_path = detect_cookies_path(cookies_cli)
    if cookies_cli and not cookies_path:
        print("⚠️  Đường dẫn cookies từ --cookies không tồn tại, tiếp tục chạy không dùng cookies.")
    elif os.getenv("YT_COOKIES") and not cookies_path:
        print("⚠️  Biến môi trường YT_COOKIES không trỏ tới file hợp lệ, tiếp tục chạy không dùng cookies.")
    download_all(urls, mode, cookies_path, style)


if __name__ == "__main__":
    main()
