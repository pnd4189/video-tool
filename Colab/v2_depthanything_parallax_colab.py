# @title VideoTool Colab — V2: DepthAnything V2 · 2.5D parallax (GPU)
# =====================================================================
# DÁN TOÀN BỘ block này vào MỘT cell Colab rồi Run. (Runtime > GPU)
# Workflow MỚI (đang update): ảnh tĩnh -> depth map (DepthAnything V2) ->
# parallax 2.5D (warp theo độ sâu, GPU) -> ghép theo voice + nhạc nền -> mp4 16:9.
#
# Input: link/đường dẫn 1 folder Google Drive chứa asset:
#   voice.wav|mp3|m4a (bắt buộc) · Image/ hoặc media/ (ảnh) · music/ (tùy chọn)
# Lần chạy đầu tải model + wheel về Google Drive; lần sau load lại, KHÔNG tải lại.
# =====================================================================
import os, sys, glob, math, time, subprocess, shutil, re

# ---- 1. Cache bền vững trên Google Drive (tải 1 lần) ----------------
CACHE = "/content/drive/MyDrive/videotool_colab_cache"
os.environ["PIP_CACHE_DIR"] = f"{CACHE}/pip"     # wheel cache -> không tải lại
os.environ["HF_HOME"]       = f"{CACHE}/hf"       # model HuggingFace -> không tải lại
os.environ["TORCH_HOME"]    = f"{CACHE}/torch"

from google.colab import drive
drive.mount("/content/drive")
for d in (CACHE, os.environ["PIP_CACHE_DIR"], os.environ["HF_HOME"], os.environ["TORCH_HOME"]):
    os.makedirs(d, exist_ok=True)

def sh(cmd):
    print("+", cmd)
    subprocess.run(cmd, shell=True, check=True)

# ---- 2. Deps (torch + CUDA đã có sẵn trên Colab) -------------------
sh("apt-get -qq install -y ffmpeg >/dev/null 2>&1 || true")
sh("pip -q install transformers gradio gdown natsort pillow")

import torch, numpy as np
from PIL import Image
from natsort import natsorted
from transformers import pipeline
import gradio as gr

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
print("Device:", DEVICE, "| GPU:", torch.cuda.get_device_name(0) if DEVICE == "cuda" else "—")

# ---- 3. Model depth (cache trên Drive qua HF_HOME) -----------------
_DEPTH = pipeline("depth-estimation",
                  model="depth-anything/Depth-Anything-V2-Small-hf",
                  device=0 if DEVICE == "cuda" else -1)

W, H = 1920, 1080
AUDIO_EXT = (".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg")
IMG_EXT   = (".jpg", ".jpeg", ".png", ".webp")

def ffprobe_dur(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nk=1:nw=1", path],
        capture_output=True, text=True).stdout.strip()
    return float(out) if out else 0.0

def fit_crop(im, w, h):
    iw, ih = im.size
    s = max(w / iw, h / ih)
    im = im.resize((round(iw * s), round(ih * s)), Image.LANCZOS)
    iw, ih = im.size
    l, t = (iw - w) // 2, (ih - h) // 2
    return im.crop((l, t, l + w, t + h))

def depth_of(pil_img):
    # resize nhỏ trước khi đoán depth -> nhanh hơn nhiều, chất lượng đủ
    small = pil_img.copy()
    small.thumbnail((1280, 1280), Image.LANCZOS)
    d = _DEPTH(small)["depth"]
    return fit_crop(d.convert("L"), W, H)

def render_clip(img_path, dur, fps, parallax_px, zoom, out_path):
    """Render 1 clip parallax 2.5D từ 1 ảnh, dùng torch grid_sample (bilinear, GPU)."""
    pil = Image.open(img_path).convert("RGB")
    img = torch.from_numpy(np.asarray(fit_crop(pil, W, H))).to(DEVICE).float().permute(2, 0, 1)[None] / 255.0
    dep = torch.from_numpy(np.asarray(depth_of(pil), dtype=np.float32)).to(DEVICE)
    dep = (dep - dep.min()) / (dep.max() - dep.min() + 1e-6)          # 0..1, 1 = gần
    ys, xs = torch.meshgrid(torch.linspace(-1, 1, H, device=DEVICE),
                            torch.linspace(-1, 1, W, device=DEVICE), indexing="ij")
    ff = subprocess.Popen(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
         "-s", f"{W}x{H}", "-r", str(fps), "-i", "-", "-an",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", out_path],
        stdin=subprocess.PIPE)
    n = max(1, int(dur * fps))
    px_x, px_y = parallax_px / (W / 2.0), (parallax_px * 0.5) / (H / 2.0)
    for i in range(n):
        ph = 2 * math.pi * i / n
        ox, oy = math.sin(ph) * px_x, math.cos(ph) * px_y          # orbit camera
        gx = xs / zoom + ox * dep
        gy = ys / zoom + oy * dep
        grid = torch.stack((gx, gy), dim=-1)[None]
        warp = torch.nn.functional.grid_sample(img, grid, mode="bilinear",
                                               padding_mode="border", align_corners=True)
        frame = (warp[0].permute(1, 2, 0).clamp(0, 1) * 255).to(torch.uint8).cpu().numpy()
        ff.stdin.write(frame.tobytes())
    ff.stdin.close(); ff.wait()

def find_assets(folder):
    def all_files(sub=""):
        base = os.path.join(folder, sub) if sub else folder
        return [os.path.join(base, f) for f in os.listdir(base)] if os.path.isdir(base) else []
    voice = None
    for name in ("voice.wav", "voice.mp3", "voice.m4a"):
        if os.path.exists(os.path.join(folder, name)):
            voice = os.path.join(folder, name); break
    if not voice:
        cand = [f for f in all_files() if f.lower().endswith(AUDIO_EXT)]
        voice = natsorted(cand)[0] if cand else None
    imgs = []
    for sub in ("Image", "media", "images", ""):
        d = os.path.join(folder, sub) if sub else folder
        if os.path.isdir(d):
            got = [os.path.join(d, f) for f in os.listdir(d) if f.lower().endswith(IMG_EXT)]
            if got:
                imgs = natsorted(got); break
    music = []
    md = os.path.join(folder, "music")
    if os.path.isdir(md):
        music = natsorted([os.path.join(md, f) for f in os.listdir(md) if f.lower().endswith(AUDIO_EXT)])
    return voice, imgs, music

def resolve_folder(inp):
    inp = inp.strip()
    if inp.startswith("http"):
        dst = "/content/job_assets"
        shutil.rmtree(dst, ignore_errors=True)
        sh(f"gdown --folder '{inp}' -O '{dst}' --remaining-ok")
        subs = [os.path.join(dst, d) for d in os.listdir(dst)]
        subs = [s for s in subs if os.path.isdir(s)]
        return subs[0] if len(subs) == 1 else dst
    if inp.startswith("/content/drive"):
        return inp
    return os.path.join("/content/drive/MyDrive", inp)

def mux_audio(silent_mp4, voice, music, out_path, music_db=-30):
    if music:
        ml = "/content/_music.m4a"
        if len(music) > 1:
            lst = "/content/_m.txt"
            open(lst, "w").write("".join(f"file '{m}'\n" for m in music))
            sh(f"ffmpeg -y -loglevel error -f concat -safe 0 -i {lst} -c copy {ml} || "
               f"ffmpeg -y -loglevel error -f concat -safe 0 -i {lst} {ml}")
        else:
            ml = music[0]
        sh(f"ffmpeg -y -loglevel error -i '{silent_mp4}' -i '{voice}' -stream_loop -1 -i '{ml}' "
           f"-filter_complex \"[2:a]volume={music_db}dB[m];[1:a][m]amix=inputs=2:duration=first[a]\" "
           f"-map 0:v -map '[a]' -c:v copy -c:a aac -shortest '{out_path}'")
    else:
        sh(f"ffmpeg -y -loglevel error -i '{silent_mp4}' -i '{voice}' "
           f"-map 0:v -map 1:a -c:v copy -c:a aac -shortest '{out_path}'")

def build(folder_input, parallax_px, zoom, fps, progress=gr.Progress()):
    folder = resolve_folder(folder_input)
    voice, imgs, music = find_assets(folder)
    if not voice or not imgs:
        return None, f"❌ Thiếu asset. voice={voice}, #ảnh={len(imgs)} tại {folder}"
    dur = ffprobe_dur(voice)
    per = dur / len(imgs)
    work = "/content/_clips"; shutil.rmtree(work, ignore_errors=True); os.makedirs(work)
    clips = []
    t0 = time.time()
    for i, im in enumerate(imgs):
        progress((i + 1) / len(imgs), desc=f"Parallax {i+1}/{len(imgs)}")
        out = f"{work}/c{i:04d}.mp4"
        render_clip(im, per, fps, parallax_px, zoom, out)
        clips.append(out)
    lst = f"{work}/list.txt"
    open(lst, "w").write("".join(f"file '{c}'\n" for c in clips))
    silent = "/content/_silent.mp4"
    sh(f"ffmpeg -y -loglevel error -f concat -safe 0 -i {lst} -c copy {silent}")
    os.makedirs(f"{folder}/Output", exist_ok=True)
    out_path = f"{folder}/Output/v2_depthanything_16x9.mp4"
    mux_audio(silent, voice, music, out_path)
    msg = (f"✅ {out_path}\n{len(imgs)} ảnh · {dur:.0f}s · {per:.1f}s/ảnh · "
           f"render {time.time()-t0:.0f}s · nhạc={len(music)} track")
    return out_path, msg

with gr.Blocks(title="VideoTool V2 — DepthAnything parallax") as demo:
    gr.Markdown("## V2 · DepthAnything V2 — 2.5D parallax (GPU)\n"
                "Nhập path Drive (`/content/drive/MyDrive/...`) hoặc link folder Drive.")
    inp = gr.Textbox(label="Folder asset (Drive path hoặc URL)",
                     value="/content/drive/MyDrive/")
    with gr.Row():
        px = gr.Slider(10, 90, 45, step=5, label="Biên độ parallax (px)")
        zm = gr.Slider(1.0, 1.15, 1.06, step=0.01, label="Zoom (giấu mép)")
        fp = gr.Slider(24, 30, 30, step=1, label="FPS")
    btn = gr.Button("Render", variant="primary")
    vid = gr.Video(label="Kết quả")
    log = gr.Textbox(label="Log")
    btn.click(build, [inp, px, zm, fp], [vid, log])

demo.launch(share=True, debug=True)
