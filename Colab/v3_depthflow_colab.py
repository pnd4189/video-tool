# @title VideoTool Colab — V3: DepthFlow · 2.5D parallax (GPU, thử nghiệm)
# =====================================================================
# DÁN TOÀN BỘ block này vào MỘT cell Colab rồi Run. (Runtime > GPU)
# Dùng DepthFlow (shader GLSL trên GPU) để biến ảnh tĩnh -> clip parallax 2.5D
# chất lượng cao (xử lý che khuất tốt hơn warp thường), rồi ghép theo voice + nhạc.
#
# ⚠️ DepthFlow đòi portaudio (cài bằng apt) + GL context headless. Colab có GPU nên
#    chạy được, nhưng cú pháp CLI DepthFlow đổi theo phiên bản — nếu lỗi, xem
#    `!depthflow --help` rồi sửa hàm depthflow_clip() cho khớp (1 dòng).
#
# Input: link/đường dẫn folder Drive: voice.* · Image/ hoặc media/ · music/ (tùy chọn)
# Lần đầu cài deps + tải model về Drive; lần sau load lại, không tải lại.
# =====================================================================
import os, sys, glob, shutil, subprocess, time

CACHE = "/content/drive/MyDrive/videotool_colab_cache"
os.environ["PIP_CACHE_DIR"]   = f"{CACHE}/pip"
os.environ["HF_HOME"]         = f"{CACHE}/hf"
os.environ["TORCH_HOME"]      = f"{CACHE}/torch"
os.environ["XDG_CACHE_HOME"]  = f"{CACHE}/xdg"     # DepthFlow lưu model depth ở đây
os.environ["WINDOW_BACKEND"]  = "headless"          # render không cần màn hình
os.environ["SHADERFLOW_BACKEND"] = "headless"

from google.colab import drive
drive.mount("/content/drive")
for d in (CACHE, os.environ["PIP_CACHE_DIR"], os.environ["HF_HOME"],
          os.environ["TORCH_HOME"], os.environ["XDG_CACHE_HOME"]):
    os.makedirs(d, exist_ok=True)

def sh(cmd, check=True):
    print("+", cmd); return subprocess.run(cmd, shell=True, check=check)

sh("apt-get -qq install -y ffmpeg portaudio19-dev >/dev/null 2>&1 || true")
sh("pip -q install depthflow gradio gdown natsort pillow")

from natsort import natsorted
import gradio as gr

W, H = 1920, 1080
AUDIO_EXT = (".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg")
IMG_EXT   = (".jpg", ".jpeg", ".png", ".webp")

def ffprobe_dur(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=nk=1:nw=1", path], capture_output=True, text=True).stdout.strip()
    return float(out) if out else 0.0

def depthflow_clip(img, dur, fps, out):
    """Gọi DepthFlow render 1 clip. Thử 2 dạng CLI phổ biến; chỉnh tại đây nếu phiên bản khác."""
    forms = [
        f"depthflow input --image '{img}' main --time {dur:.2f} --fps {fps} "
        f"--width {W} --height {H} --output '{out}'",
        f"depthflow input -i '{img}' main -t {dur:.2f} --fps {fps} -o '{out}'",
    ]
    for cmd in forms:
        r = subprocess.run(cmd, shell=True)
        if r.returncode == 0 and os.path.exists(out):
            return True
    return False

def find_assets(folder):
    voice = None
    for name in ("voice.wav", "voice.mp3", "voice.m4a"):
        if os.path.exists(os.path.join(folder, name)):
            voice = os.path.join(folder, name); break
    if not voice:
        cand = natsorted([os.path.join(folder, f) for f in os.listdir(folder)
                          if f.lower().endswith(AUDIO_EXT)])
        voice = cand[0] if cand else None
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
        dst = "/content/job_src"; shutil.rmtree(dst, ignore_errors=True)
        sh(f"gdown --folder '{inp}' -O '{dst}' --remaining-ok")
        subs = [os.path.join(dst, d) for d in os.listdir(dst) if os.path.isdir(os.path.join(dst, d))]
        return subs[0] if len(subs) == 1 else dst
    if inp.startswith("/content/drive"):
        return inp
    return os.path.join("/content/drive/MyDrive", inp)

def mux_audio(silent_mp4, voice, music, out_path, music_db=-30):
    if music:
        if len(music) > 1:
            lst = "/content/_m.txt"; open(lst, "w").write("".join(f"file '{m}'\n" for m in music))
            ml = "/content/_music.m4a"
            sh(f"ffmpeg -y -loglevel error -f concat -safe 0 -i {lst} {ml}")
        else:
            ml = music[0]
        sh(f"ffmpeg -y -loglevel error -i '{silent_mp4}' -i '{voice}' -stream_loop -1 -i '{ml}' "
           f"-filter_complex \"[2:a]volume={music_db}dB[m];[1:a][m]amix=inputs=2:duration=first[a]\" "
           f"-map 0:v -map '[a]' -c:v copy -c:a aac -shortest '{out_path}'")
    else:
        sh(f"ffmpeg -y -loglevel error -i '{silent_mp4}' -i '{voice}' "
           f"-map 0:v -map 1:a -c:v copy -c:a aac -shortest '{out_path}'")

def build(folder_input, fps, progress=gr.Progress()):
    folder = resolve_folder(folder_input)
    voice, imgs, music = find_assets(folder)
    if not voice or not imgs:
        return None, f"❌ Thiếu asset. voice={voice}, #ảnh={len(imgs)}"
    dur = ffprobe_dur(voice); per = dur / len(imgs)
    work = "/content/_clips"; shutil.rmtree(work, ignore_errors=True); os.makedirs(work)
    clips = []; t0 = time.time()
    for i, im in enumerate(imgs):
        progress((i + 1) / len(imgs), desc=f"DepthFlow {i+1}/{len(imgs)}")
        out = f"{work}/c{i:04d}.mp4"
        if not depthflow_clip(im, per, fps, out):
            return None, ("❌ DepthFlow lỗi ở ảnh %d. Chạy `!depthflow --help` để xem cú pháp "
                          "rồi sửa hàm depthflow_clip()." % i)
        clips.append(out)
    # chuẩn hoá fps/size trước khi concat (clip DepthFlow có thể khác thông số)
    norm = []
    for i, c in enumerate(clips):
        nc = f"{work}/n{i:04d}.mp4"
        sh(f"ffmpeg -y -loglevel error -i '{c}' -vf scale={W}:{H},fps={fps} "
           f"-c:v libx264 -preset veryfast -crf 20 -pix_fmt yuv420p -an '{nc}'")
        norm.append(nc)
    lst = f"{work}/list.txt"; open(lst, "w").write("".join(f"file '{c}'\n" for c in norm))
    silent = "/content/_silent.mp4"
    sh(f"ffmpeg -y -loglevel error -f concat -safe 0 -i {lst} -c copy {silent}")
    os.makedirs(f"{folder}/Output", exist_ok=True)
    out_path = f"{folder}/Output/v3_depthflow_16x9.mp4"
    mux_audio(silent, voice, music, out_path)
    return out_path, (f"✅ {out_path}\n{len(imgs)} ảnh · {dur:.0f}s · {per:.1f}s/ảnh · "
                      f"render {time.time()-t0:.0f}s")

with gr.Blocks(title="VideoTool V3 — DepthFlow") as demo:
    gr.Markdown("## V3 · DepthFlow — 2.5D parallax (GPU, thử nghiệm)\n"
                "Nhập path Drive hoặc link folder Drive. Nếu DepthFlow lỗi cú pháp, "
                "chạy `!depthflow --help` và sửa `depthflow_clip()`.")
    inp = gr.Textbox(label="Folder asset (Drive path hoặc URL)", value="/content/drive/MyDrive/")
    fp = gr.Slider(24, 30, 30, step=1, label="FPS")
    btn = gr.Button("Render", variant="primary")
    vid = gr.Video(label="Kết quả")
    log = gr.Textbox(label="Log")
    btn.click(build, [inp, fp], [vid, log])

demo.launch(share=True, debug=True)
