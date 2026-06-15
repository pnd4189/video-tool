# @title VideoTool Colab — V1: Workflow HIỆN TẠI (Ken Burns / zoompan)
# =====================================================================
# DÁN TOÀN BỘ block này vào MỘT cell Colab rồi Run.
# Chạy ĐÚNG pipeline của tool hiện tại (clone repo pnd4189/video-tool, cài qua pip)
# theo 4 bước trong CLAUDE.md: init-job -> storyboard auto -> validate -> render -> package.
# Motion = zoompan Ken Burns (KHÔNG depth). Đây là baseline để so sánh với V2/V3.
#
# Input: link/đường dẫn 1 folder Google Drive chứa asset:
#   voice.wav|mp3|m4a · Image/ hoặc media/ (ảnh) · music/ (tùy chọn) · Video/ (tùy chọn b-roll)
# Lần đầu clone repo + cài deps về Drive; lần sau git pull, không cài lại từ đầu.
# =====================================================================
import os, sys, glob, shutil, subprocess

CACHE = "/content/drive/MyDrive/videotool_colab_cache"
REPO  = f"{CACHE}/repo"
os.environ["PIP_CACHE_DIR"] = f"{CACHE}/pip"
os.environ["HF_HOME"]       = f"{CACHE}/hf"

from google.colab import drive
drive.mount("/content/drive")
for d in (CACHE, os.environ["PIP_CACHE_DIR"], os.environ["HF_HOME"]):
    os.makedirs(d, exist_ok=True)

def sh(cmd, check=True):
    print("+", cmd); return subprocess.run(cmd, shell=True, check=check)

sh("apt-get -qq install -y ffmpeg >/dev/null 2>&1 || true")
sh("pip -q install gradio gdown natsort")

# clone/update repo trên Drive (tải 1 lần) rồi cài editable
if not os.path.isdir(REPO):
    sh(f"git clone --depth 1 https://github.com/pnd4189/video-tool '{REPO}'")
else:
    sh(f"cd '{REPO}' && git pull --ff-only", check=False)
sh(f"pip -q install -e '{REPO}'")

from natsort import natsorted
import gradio as gr

AUDIO_EXT = (".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg")
IMG_EXT   = (".jpg", ".jpeg", ".png", ".webp")
VID_EXT   = (".mp4", ".mov", ".mkv", ".webm")

def resolve_folder(inp):
    inp = inp.strip()
    if inp.startswith("http"):
        dst = "/content/job_src"; shutil.rmtree(dst, ignore_errors=True)
        sh(f"gdown --folder '{inp}' -O '{dst}' --remaining-ok")
        subs = [os.path.join(dst, d) for d in os.listdir(dst) if os.path.isdir(os.path.join(dst, d))]
        return subs[0] if len(subs) == 1 else dst
    if inp.startswith("/content/drive"):
        return inp
    return os.path.join("/content/drive/MyDrive", inp)

def stage(folder):
    """Copy asset ra /content (đệm ghi được) theo layout init-job mong đợi. KHÔNG sửa Drive."""
    job = "/content/job"; shutil.rmtree(job, ignore_errors=True)
    os.makedirs(f"{job}/media", exist_ok=True)
    # voice
    voice = None
    for name in ("voice.wav", "voice.mp3", "voice.m4a"):
        if os.path.exists(os.path.join(folder, name)):
            voice = os.path.join(folder, name); break
    if not voice:
        cand = natsorted([os.path.join(folder, f) for f in os.listdir(folder)
                          if f.lower().endswith(AUDIO_EXT)])
        voice = cand[0] if cand else None
    if voice:
        shutil.copy(voice, f"{job}/voice{os.path.splitext(voice)[1]}")
    # images
    for sub in ("Image", "media", "images", ""):
        d = os.path.join(folder, sub) if sub else folder
        if os.path.isdir(d):
            got = natsorted([f for f in os.listdir(d) if f.lower().endswith(IMG_EXT)])
            if got:
                for f in got:
                    shutil.copy(os.path.join(d, f), f"{job}/media/{f}")
                break
    # music
    md = os.path.join(folder, "music")
    if os.path.isdir(md):
        os.makedirs(f"{job}/music", exist_ok=True)
        for f in natsorted(os.listdir(md)):
            if f.lower().endswith(AUDIO_EXT):
                shutil.copy(os.path.join(md, f), f"{job}/music/{f}")
    # video b-roll
    vd = os.path.join(folder, "Video")
    has_vid = False
    if os.path.isdir(vd):
        os.makedirs(f"{job}/Video", exist_ok=True)
        for f in natsorted(os.listdir(vd)):
            if f.lower().endswith(VID_EXT):
                shutil.copy(os.path.join(vd, f), f"{job}/Video/{f}"); has_vid = True
    vname = [f for f in os.listdir(job) if f.startswith("voice")]
    return job, (vname[0] if vname else None), os.path.isdir(f"{job}/music"), has_vid

def build(folder_input, progress=gr.Progress()):
    folder = resolve_folder(folder_input)
    progress(0.1, desc="Staging assets")
    job, voice, has_music, has_vid = stage(folder)
    if not voice:
        return None, f"❌ Không thấy voice trong {folder}"
    jy = f"{job}/job.yaml"
    music_arg = "--music music" if has_music else ""
    sh(f"cd '{job}' && videotool init-job . --voice {voice} --media media {music_arg}")
    # Pitfall fix: licensed-only -> allow-missing-local; captions off (CLAUDE.md)
    sh(f"sed -i -e 's/policy: licensed-only/policy: allow-missing-local/' "
       f"-e '/captions:/,/^[^ ]/ s/mode: srt-only/mode: off/' '{jy}'", check=False)
    sh(f"grep -q 'captions:' '{jy}' || printf '\\ncaptions:\\n  mode: off\\n' >> '{jy}'", check=False)
    progress(0.3, desc="Storyboard")
    vid_arg = f"--videos-dir '{job}/Video'" if has_vid else ""
    sh(f"videotool storyboard auto '{jy}' --images-dir '{job}/media' {vid_arg}")
    sh(f"videotool validate '{jy}'")
    progress(0.5, desc="Render (zoompan)")
    sh(f"videotool render '{jy}' --preset youtube-16x9")
    progress(0.9, desc="Package")
    sh(f"videotool package '{jy}'", check=False)
    out = f"{job}/outputs/youtube-16x9.mp4"
    if not os.path.exists(out):
        cand = glob.glob(f"{job}/outputs/*.mp4")
        out = cand[0] if cand else None
    if out:
        os.makedirs(f"{folder}/Output", exist_ok=True)
        dst = f"{folder}/Output/v1_current_16x9.mp4"
        shutil.copy(out, dst)
        return dst, f"✅ {dst}"
    return None, "❌ Không thấy output mp4 — xem log ở trên."

with gr.Blocks(title="VideoTool V1 — Current workflow") as demo:
    gr.Markdown("## V1 · Workflow hiện tại (Ken Burns / zoompan)\n"
                "Chạy đúng `videotool` CLI. Nhập path Drive hoặc link folder Drive.")
    inp = gr.Textbox(label="Folder asset (Drive path hoặc URL)",
                     value="/content/drive/MyDrive/")
    btn = gr.Button("Render", variant="primary")
    vid = gr.Video(label="Kết quả")
    log = gr.Textbox(label="Log")
    btn.click(build, [inp], [vid, log])

demo.launch(share=True, debug=True)
