#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#Tải->convert->đẩy->xóa

import sys
import os
import re
import time
from pathlib import Path
from typing import List, Optional, Tuple, Dict

from yt_dlp import YoutubeDL
from huggingface_hub import HfApi, create_repo, hf_hub_url, upload_file

# ---------- Config loader: TOML (py311+ dùng tomllib; thấp hơn dùng 'toml') ----------
def load_toml(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        import tomllib  # Py 3.11+
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except ModuleNotFoundError:
        import toml  # pip install toml (nếu <3.11)
        return toml.loads(path.read_text(encoding="utf-8"))

# ---------- Đường dẫn mặc định ----------
ROOT = Path.cwd()
CONF_FILE = ROOT / "run_hf.toml"
DOWNLOAD_DIR = ROOT / "downloads"
DOWNLOAD_DIR.mkdir(exist_ok=True)
LINK_FILE = ROOT / "link.txt"

# ---------- Helper in/out ----------
def parse_cli(argv: List[str]) -> Tuple[Dict[str, str], List[str]]:
    """
    Trả về (overrides, cli_urls). overrides chứa các trường người dùng truyền bằng CLI.
    """
    ov: Dict[str, str] = {}
    urls: List[str] = []
    i = 1
    while i < len(argv):
        a = argv[i]
        if a in ("-h", "--help"):
            print_help_and_exit()
        if a == "--hf-repo-id":
            ov["hf.repo_id"] = argv[i+1]; i += 2; continue
        if a == "--hf-repo-type":
            ov["hf.repo_type"] = argv[i+1]; i += 2; continue
        if a == "--hf-branch":
            ov["hf.branch"] = argv[i+1]; i += 2; continue
        if a == "--hf-path-prefix":
            ov["hf.path_prefix"] = argv[i+1]; i += 2; continue
        if a == "--cookies":
            ov["cookies.path"] = argv[i+1]; i += 2; continue
        urls.append(a); i += 1
    return ov, urls

def print_help_and_exit():
    print(rf"""
YouTube -> Hugging Face Uploader  (config-first, per-item upload)

Cách dùng tối giản:
  python {Path(__file__).name}

Ưu tiên cấu hình (cao -> thấp):
  CLI (--hf-..., --cookies)  >  ENV (HF_TOKEN, YT_COOKIES)  >  run_hf.toml  >  mặc định

Tuỳ chọn CLI (ghi đè config):
  --hf-repo-id USER/REPO
  --hf-repo-type dataset|model|space
  --hf-branch main
  --hf-path-prefix mp4/
  --cookies path/to/cookies.txt

ENV hỗ trợ:
  HF_TOKEN, HF_REPO_ID, HF_REPO_TYPE, HF_BRANCH, HF_PATH_PREFIX, YT_COOKIES

Link đầu vào:
  - Tham số CLI (URL1 URL2 ...)
  - Hoặc file link.txt (mỗi dòng 1 URL)
  - Hoặc dán tay khi chạy

Chọn đầu ra:
  1) MP4 (best)  2) MP3  3) WAV

Config file: run_hf.toml (đặt cạnh script)
""")
    sys.exit(0)

def merge_config(cli_ov: Dict[str, str], conf: dict) -> dict:
    """Hợp nhất theo ưu tiên: CLI > ENV > TOML > default"""
    # 1) Bắt đầu từ TOML
    merged = {
        "hf": {
            "token": conf.get("hf", {}).get("token", "").strip(),
            "repo_id": conf.get("hf", {}).get("repo_id", "").strip(),
            "repo_type": conf.get("hf", {}).get("repo_type", "dataset").strip() or "dataset",
            "branch": conf.get("hf", {}).get("branch", "main").strip() or "main",
            "path_prefix": conf.get("hf", {}).get("path_prefix", "").strip(),
        },
        "cookies": {
            "path": conf.get("cookies", {}).get("path", "").strip(),
        },
        "downloader": {
            "ratelimit": int(conf.get("downloader", {}).get("ratelimit", 2_000_000)),
            "sleep_interval": float(conf.get("downloader", {}).get("sleep_interval", 2)),
            "max_sleep_interval": float(conf.get("downloader", {}).get("max_sleep_interval", 5)),
            "sleep_requests": float(conf.get("downloader", {}).get("sleep_requests", 0.5)),
        }
    }

    # 2) ENV ghi đè TOML (nếu có)
    env_overrides = {
        "hf.token": os.getenv("HF_TOKEN", "").strip(),
        "hf.repo_id": os.getenv("HF_REPO_ID", "").strip(),
        "hf.repo_type": os.getenv("HF_REPO_TYPE", "").strip(),
        "hf.branch": os.getenv("HF_BRANCH", "").strip(),
        "hf.path_prefix": os.getenv("HF_PATH_PREFIX", "").strip(),
        "cookies.path": os.getenv("YT_COOKIES", "").strip(),
    }
    for k, v in env_overrides.items():
        if v:
            sect, key = k.split(".")
            merged[sect][key] = v

    # 3) CLI ghi đè tất cả
    for k, v in cli_ov.items():
        sect, key = k.split(".")
        merged[sect][key] = v

    return merged

def choose_mode() -> str:
    print("\nChọn chế độ xuất:")
    print("  1) Video MP4 (chất lượng cao nhất)")
    print("  2) Âm thanh MP3")
    print("  3) Âm thanh WAV")
    while True:
        c = input("Nhập 1 / 2 / 3: ").strip()
        if c in {"1", "2", "3"}:
            return c
        print("Lựa chọn không hợp lệ.")

def collect_urls(cli_urls: List[str]) -> List[str]:
    if cli_urls:
        return cli_urls
    if LINK_FILE.exists():
        print(f"Đọc link từ {LINK_FILE} ...")
        urls = [ln.strip() for ln in LINK_FILE.read_text(encoding="utf-8").splitlines() if ln.strip()]
        if urls: return urls
    print("Nhập 1 hoặc nhiều link (cách nhau bởi khoảng trắng / xuống dòng). Kết thúc bằng dòng trống:")
    buf = []
    while True:
        try:
            line = input().strip()
        except EOFError:
            break
        if not line: break
        buf += re.split(r"\s+", line)
    urls = [u for u in buf if u]
    if not urls:
        print("Không có URL nào. Thoát."); sys.exit(1)
    return urls

# ---------- yt-dlp ----------
def progress_hook(d):
    if d.get("status") == "downloading":
        p = d.get("_percent_str", "").strip()
        spd = d.get("speed")
        eta = d.get("eta")
        print(f"Đang tải: {p:<6} | Tốc độ: {spd or '-':<10} | ETA: {eta or '-'}", end="\r", flush=True)
    elif d.get("status") == "finished":
        print("\n✓ Tải xong, đang xử lý (ffmpeg)...")

def make_opts(mode: str, cookies_path: Optional[str], dl_cfg: dict):
    common = {
        "outtmpl": str(DOWNLOAD_DIR / "%(title)s [%(id)s].%(ext)s"),
        "ignoreerrors": True,
        "noplaylist": False,
        "concurrent_fragment_downloads": 4,
        "retries": 10,
        "fragment_retries": 10,
        "http_chunk_size": 10 * 1024 * 1024,
        "progress_hooks": [progress_hook],
        "trim_file_name": 240,
        "quiet": False,
        "no_warnings": True,
        # lịch sự
        "ratelimit": dl_cfg.get("ratelimit", 2_000_000),
        "sleep_interval": dl_cfg.get("sleep_interval", 2),
        "max_sleep_interval": dl_cfg.get("max_sleep_interval", 5),
        "sleep_requests": dl_cfg.get("sleep_requests", 0.5),
    }
    if cookies_path:
        common["cookiefile"] = cookies_path

    if mode == "1":
        return {
            **common,
            "format": ("bestvideo[ext=mp4][vcodec*=avc]/bestvideo[vcodec*=avc]+bestaudio[ext=m4a]/"
                       "best[ext=mp4]/best"),
            "merge_output_format": "mp4",
            "postprocessors": [
                {"key": "FFmpegVideoConvertor", "preferedformat": "mp4"},
                {"key": "FFmpegMetadata"},
            ],
        }
    # audio
    target = "mp3" if mode == "2" else "wav"
    return {
        **common,
        "format": "bestaudio/best",
        "postprocessors": [
            {"key": "FFmpegExtractAudio", "preferredcodec": target, "preferredquality": "0"},
            {"key": "FFmpegMetadata"},
        ],
        "prefer_ffmpeg": True,
    }

# ---------- HF ----------
def ensure_hf_repo(api: HfApi, token: str, repo_id: str, repo_type: str):
    create_repo(repo_id=repo_id, repo_type=repo_type, token=token, exist_ok=True)

def hf_upload(api: HfApi, token: str, repo_id: str, repo_type: str, branch: str, fpath: Path, path_in_repo: str) -> str:
    upload_file(
        path_or_fileobj=str(fpath),
        path_in_repo=path_in_repo,
        repo_id=repo_id,
        repo_type=repo_type,
        token=token,
        revision=branch,
    )
    return hf_hub_url(repo_id=repo_id, filename=path_in_repo, repo_type=repo_type, revision=branch)

def infer_path_in_repo(prefix: str, name: str) -> str:
    prefix = (prefix or "").strip().lstrip("/")
    return f"{prefix}/{name}" if prefix else name

# ---------- Orchestrate (per-item: download -> upload -> delete) ----------
def run_pipeline(urls: List[str], mode: str, cfg: dict):
    hf = cfg["hf"]; cookies = cfg["cookies"]; dl_cfg = cfg["downloader"]
    token = hf.get("token") or os.getenv("HF_TOKEN", "").strip()
    if not token:
        print("❌ Thiếu HF token (điền vào run_hf.toml [hf].token hoặc ENV HF_TOKEN)."); sys.exit(2)
    repo_id = hf.get("repo_id") or os.getenv("HF_REPO_ID", "")
    if not repo_id:
        print("❌ Thiếu repo_id (điền [hf].repo_id hoặc ENV HF_REPO_ID)."); sys.exit(2)
    repo_type = hf.get("repo_type") or os.getenv("HF_REPO_TYPE", "dataset")
    branch = hf.get("branch") or os.getenv("HF_BRANCH", "main")
    prefix = hf.get("path_prefix") or os.getenv("HF_PATH_PREFIX", "")

    cookies_path = cookies.get("path") or os.getenv("YT_COOKIES", "")
    if cookies_path and not Path(cookies_path).exists():
        print(f"⚠️  Cookies không tồn tại: {cookies_path}. Bỏ qua.")
        cookies_path = None
    elif not cookies_path:
        cookies_path = None

    ydl_opts = make_opts(mode, cookies_path, dl_cfg)

    kind = "MP4" if mode == "1" else ("MP3" if mode == "2" else "WAV")
    print("\n======== THÔNG TIN TÁC VỤ ========")
    print("Đầu ra    :", kind)
    print("Local     :", DOWNLOAD_DIR.resolve(), "(tạm)")
    print("Cookies   :", cookies_path or "(không dùng)")
    print("HF repo   :", repo_id, f"({repo_type})")
    print("HF branch :", branch)
    print("HF prefix :", prefix or "(root)")
    print("Số link   :", len(urls))
    print("===================================\n")

    api = HfApi()
    ensure_hf_repo(api, token, repo_id, repo_type)

    # ---- Lặp từng URL: tải -> đẩy ngay -> xoá file local ----
    with YoutubeDL(ydl_opts) as ydl:
        for i, url in enumerate(urls, 1):
            print(f"\n----- [{i}/{len(urls)}] {url}")

            # Ghi nhận danh sách file hiện có, để sau khi tải xong xác định đúng file mới sinh
            before = {p.resolve() for p in DOWNLOAD_DIR.glob("*")}

            try:
                ydl.download([url])
            except Exception as e:
                msg = str(e).lower()
                print(f"❌ Lỗi tải: {e}")
                if "429" in msg or "too many requests" in msg or "http error 403" in msg:
                    print("⚠️  Rate-limit nghi ngờ. Nghỉ 5 phút rồi tiếp...")
                    time.sleep(300)
                continue

            # Đợi rất ngắn cho postprocessor (ffmpeg) flush file ra đĩa
            time.sleep(0.5)

            # Xác định các file mới (sau convert)
            after = {p.resolve() for p in DOWNLOAD_DIR.glob("*")}
            new_files = [p for p in sorted(after - before, key=lambda x: x.stat().st_mtime) if p.is_file()]
            if not new_files:
                print("⚠️  Không thấy file mới sau khi tải/convert.")
                continue

            # Với 1 URL YouTube, thường sinh 1 file cuối (MP4 hoặc MP3/WAV). Nhưng nếu playlist-item
            # thì yt-dlp vẫn đi từng item; ở đây cứ xử lý tất cả file mới (hiếm khi trùng thời điểm).
            for f in new_files:
                dst = infer_path_in_repo(prefix, f.name)
                try:
                    print(f"↑ Upload HF: {dst} ...")
                    url_file = hf_upload(api, token, repo_id, repo_type, branch, f, dst)
                    print(f"   ✓ {url_file}")
                except Exception as up_e:
                    print(f"   ❌ Lỗi upload: {up_e}")
                    continue

                # Xoá local NGAY khi upload xong
                try:
                    f.unlink()
                    print(f"   🧹 Xoá local: {f.name}")
                except Exception as del_e:
                    print(f"   ⚠️ Không xoá được {f.name}: {del_e}")

    print("\n✅ Hoàn tất toàn bộ danh sách (đã upload từng mục & dọn file tạm).")

# ---------- main ----------
def main():
    cli_ov, cli_urls = parse_cli(sys.argv)
    conf = load_toml(CONF_FILE)
    cfg = merge_config(cli_ov, conf)

    urls = collect_urls(cli_urls)
    mode = choose_mode()
    run_pipeline(urls, mode, cfg)

if __name__ == "__main__":
    main()
