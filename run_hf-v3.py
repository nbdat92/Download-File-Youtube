#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys, os, re, time
from pathlib import Path
from typing import List, Optional, Dict

from yt_dlp import YoutubeDL
from huggingface_hub import HfApi, create_repo, hf_hub_url, upload_file

ROOT = Path.cwd()
CONF_FILE = ROOT / "run_hf.toml"
DOWNLOAD_DIR = ROOT / "downloads"
DOWNLOAD_DIR.mkdir(exist_ok=True)
LINK_FILE = ROOT / "link.txt"

# =============== Config loader ===============
def load_toml(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        import tomllib  # Python 3.11+
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except ModuleNotFoundError:
        import toml      # pip install toml (nếu <3.11)
        return toml.loads(path.read_text(encoding="utf-8"))

# =============== Merge config ===============
def merge_config(conf: dict) -> dict:
    """Ưu tiên: ENV > TOML > default"""
    hf = conf.get("hf", {}) if conf else {}
    cookies = conf.get("cookies", {}) if conf else {}
    dl = conf.get("downloader", {}) if conf else {}

    merged = {
        "hf": {
            "token":       os.getenv("HF_TOKEN",       hf.get("token",       "").strip()),
            "repo_id":     os.getenv("HF_REPO_ID",     hf.get("repo_id",     "").strip()),
            "repo_type":   os.getenv("HF_REPO_TYPE",   hf.get("repo_type",   "dataset").strip() or "dataset"),
            "branch":      os.getenv("HF_BRANCH",      hf.get("branch",      "main").strip() or "main"),
            "path_prefix": os.getenv("HF_PATH_PREFIX", hf.get("path_prefix", "").strip()),
        },
        "cookies": {
            "path": os.getenv("YT_COOKIES", cookies.get("path", "").strip()),
        },
        "downloader": {
            "ratelimit":          int(dl.get("ratelimit",          2_000_000)),  # ~2MB/s
            "sleep_interval":     float(dl.get("sleep_interval",   2)),
            "max_sleep_interval": float(dl.get("max_sleep_interval",5)),
            "sleep_requests":     float(dl.get("sleep_requests",   0.5)),
        }
    }
    return merged

# =============== Hugging Face helpers ===============
def ensure_hf_repo(api: HfApi, token: str, repo_id: str, repo_type: str):
    create_repo(repo_id=repo_id, repo_type=repo_type, token=token, exist_ok=True)

def hf_upload(api: HfApi, token: str, repo_id: str, repo_type: str,
              branch: str, fpath: Path, path_in_repo: str) -> str:
    upload_file(
        path_or_fileobj=str(fpath),
        path_in_repo=path_in_repo,
        repo_id=repo_id,
        repo_type=repo_type,
        token=token,
        revision=branch,
    )
    return hf_hub_url(repo_id=repo_id, filename=path_in_repo,
                      repo_type=repo_type, revision=branch)

def infer_path_in_repo(prefix: str, name: str) -> str:
    prefix = (prefix or "").strip().lstrip("/")
    return f"{prefix}/{name}" if prefix else name

# =============== yt-dlp options (per-item upload) ===============
def make_opts(mode: str, cookies_path: Optional[str], dl_cfg: dict,
             api: HfApi, token: str, repo_id: str, repo_type: str, branch: str, prefix: str, style):

    uploaded_once = set()
    wanted_ext = {"1": "mp4", "2": "mp3", "3": "wav"}[mode]  # <— đuôi mong muốn

    def progress_hook(d):
        if d.get("status") == "downloading":
            p = (d.get("_percent_str") or "").strip()
            spd = d.get("speed"); eta = d.get("eta")
            print(f"Đang tải: {p:<6} | Tốc độ: {spd or '-':<10} | ETA: {eta or '-'}", end="\r", flush=True)
        elif d.get("status") == "finished":
            print("\n✓ Tải xong, đang xử lý (ffmpeg)...")

    def postproc_hook(d):
        if d.get("status") != "finished":
            return
        info = d.get("info_dict") or {}
        # LẤY FILE CUỐI CÙNG -> KHÔNG DÙNG 'filename' (thường là file tạm .webm/.m4a)
        candidates = [info.get("filepath"), info.get("__final_filename")]
        target = None
        for c in candidates:
            if c and Path(c).exists():
                # chỉ nhận đúng đuôi đã chọn
                if Path(c).suffix.lower().lstrip(".") == wanted_ext:
                    target = Path(c)
                    break
        if not target:
            return
        key = str(target.resolve())
        if key in uploaded_once:
            return
        uploaded_once.add(key)

        # Upload
        path_in_repo = infer_path_in_repo(prefix, target.name)
        try:
            print(f"↑ Upload HF: {path_in_repo}")
            url_file = hf_upload(api, token, repo_id, repo_type, branch, target, path_in_repo)
            print(f"   ✓ {url_file}")
        except Exception as e:
            print(f"   ❌ Lỗi upload: {e}")
            return

        # Xoá local
        try:
            target.unlink()
            print(f"   🧹 Đã xoá local: {target.name}")
        except Exception as e:
            print(f"   ⚠️ Không xoá được {target}: {e}")

    common = {
        "outtmpl": str(DOWNLOAD_DIR / "%(autonumber)s - %(title)s [%(id)s].%(ext)s"),
        "autonumber_size": int(style),
        "ignoreerrors": True,
        "noplaylist": False,
        "progress_hooks": [progress_hook],
        "postprocessor_hooks": [postproc_hook],
        "quiet": False,
        "no_warnings": True,
        "keepvideo": False,  # <— Đặt ở TOP-LEVEL (xoá file gốc sau post-processing)
        # lịch sự
        "ratelimit": dl_cfg.get("ratelimit", 2_000_000),
        "sleep_interval": dl_cfg.get("sleep_interval", 2),
        "max_sleep_interval": dl_cfg.get("max_sleep_interval", 5),
        "sleep_requests": dl_cfg.get("sleep_requests", 0.5),
    }
    if cookies_path and Path(cookies_path).exists():
        common["cookiefile"] = cookies_path

    if mode == "1":  # MP4
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
    else:           # MP3 / WAV
        target = "mp3" if mode == "2" else "wav"
        return {
            **common,
            "format": "bestaudio/best",
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": target,
                    "preferredquality": "0",
                    "nopostoverwrites": False
                    # ❌ KHÔNG đặt 'keepvideo' ở đây
                },
                {"key": "FFmpegMetadata"},
            ],
            "prefer_ffmpeg": True,
        }


# =============== Orchestrator ===============
def run_pipeline(urls: List[str], mode: str, cfg: dict, style):
    hf = cfg["hf"]; cookies = cfg["cookies"]; dl_cfg = cfg["downloader"]

    token = (hf.get("token") or "").strip()
    repo_id = (hf.get("repo_id") or "").strip()
    repo_type = (hf.get("repo_type") or "dataset").strip() or "dataset"
    branch = (hf.get("branch") or "main").strip() or "main"
    prefix = (hf.get("path_prefix") or "").strip()

    if not token or not repo_id:
        print("❌ Thiếu token hoặc repo_id (điền trong run_hf.toml hoặc đặt ENV HF_TOKEN/HF_REPO_ID).")
        sys.exit(2)

    cookies_path = (cookies.get("path") or "").strip()
    if cookies_path and not Path(cookies_path).exists():
        print(f"⚠️  Cookies không tồn tại: {cookies_path}. Bỏ qua.")
        cookies_path = None
    elif not cookies_path:
        cookies_path = None

    api = HfApi()
    ensure_hf_repo(api, token, repo_id, repo_type)

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

    opts = make_opts(mode, cookies_path, dl_cfg, api, token, repo_id, repo_type, branch, prefix, style)
    with YoutubeDL(opts) as ydl:
        ydl.download(urls)

    print("\n✅ Hoàn tất toàn bộ danh sách (đã upload từng bài & dọn file tạm).")

# =============== Run ===============
def main():
    conf = load_toml(CONF_FILE)
    cfg = merge_config(conf)

    # Thu thập URL
    urls: List[str] = []
    if LINK_FILE.exists():
        urls = [ln.strip() for ln in LINK_FILE.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if not urls:
        print("Nhập link YouTube (kết thúc bằng dòng trống):")
        buf: List[str] = []
        while True:
            line = input().strip()
            if not line:
                break
            buf += re.split(r"\s+", line)
        urls = [u for u in buf if u]
    if not urls:
        print("❌ Không có URL."); sys.exit(1)

    print("Chọn mode: 1) MP4  2) MP3  3) WAV")
    mode = input("→ ").strip()
    if mode not in {"1", "2", "3"}:
        mode = "1"
    print("\n")
    print("Chọn kiểu đánh số: 1-2-3-4-5")
    style = input("→ ").strip()
    if style not in {"1", "2", "3", "4", "5"}:
        style = "5"

    run_pipeline(urls, mode, cfg, style)

if __name__ == "__main__":
    main()
