# @title VideoTool Colab — V4: DepthFlow clips-only (GPU) → Parallax/
# =====================================================================
# DÁN TOÀN BỘ block này vào MỘT cell Colab rồi Run. (Runtime > GPU)
# Khác V3: CHỈ sinh clip parallax 2.5D cho TỪNG ảnh (loopable), KHÔNG ghép, KHÔNG audio.
# Output = folder Parallax/<tên-ảnh>.mp4. Tải Parallax/ về, up cạnh folder asset, rồi chạy
# `/parallax-video` ở local — `videotool parallax-link` sẽ khớp clip theo TÊN ẢNH (stem).
#
# ⚠️ DepthFlow đòi portaudio (apt) + GL headless. Cú pháp CLI đổi theo phiên bản — nếu lỗi,
#    chạy `!depthflow --help` rồi sửa hàm depthflow_clip() (1 dòng). Animation `circle` cho
#    quỹ đạo TUẦN HOÀN (đầu≈cuối) nên clip loop liền mạch khi local -stream_loop.
#
# Input: link/đường dẫn folder Drive chứa Image/ (hoặc media/). KHÔNG cần voice/music.
# =====================================================================
import os, shutil, subprocess, time

CACHE = "/content/drive/MyDrive/videotool_colab_cache"
os.environ["PIP_CACHE_DIR"]      = f"{CACHE}/pip"
os.environ["HF_HOME"]            = f"{CACHE}/hf"
os.environ["TORCH_HOME"]         = f"{CACHE}/torch"
os.environ["XDG_CACHE_HOME"]     = f"{CACHE}/xdg"     # DepthFlow lưu model depth ở đây
os.environ["WINDOW_BACKEND"]     = "headless"
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
IMG_EXT = (".jpg", ".jpeg", ".png", ".webp")


def depthflow_clip(img, dur, fps, out):
    """Render 1 clip parallax loopable. `circle` = quỹ đạo tuần hoàn (loop liền mạch).
    Thử 2 dạng CLI; nếu phiên bản DepthFlow khác, chạy `!depthflow --help` rồi sửa ở đây."""
    forms = [
        f"depthflow input --image '{img}' circle main --time {dur:.2f} --fps {fps} "
        f"--width {W} --height {H} --output '{out}'",
        f"depthflow input -i '{img}' circle main -t {dur:.2f} --fps {fps} -o '{out}'",
    ]
    for cmd in forms:
        r = subprocess.run(cmd, shell=True)
        if r.returncode == 0 and os.path.exists(out):
            return True
    return False


def find_images(folder):
    for sub in ("Image", "media", "images", ""):
        d = os.path.join(folder, sub) if sub else folder
        if os.path.isdir(d):
            got = [os.path.join(d, f) for f in os.listdir(d) if f.lower().endswith(IMG_EXT)]
            if got:
                return natsorted(got)
    return []


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


def make_clips(folder_input, dur, fps, progress=gr.Progress()):
    folder = resolve_folder(folder_input)
    imgs = find_images(folder)
    if not imgs:
        return f"❌ Không thấy ảnh trong {folder} (Image/ hoặc media/)."
    out_dir = os.path.join(folder, "Parallax"); os.makedirs(out_dir, exist_ok=True)
    made = skipped = failed = 0; t0 = time.time()
    fails = []
    for i, im in enumerate(imgs):
        stem = os.path.splitext(os.path.basename(im))[0]
        out = os.path.join(out_dir, f"{stem}.mp4")     # tên = stem ảnh → contract với parallax-link
        progress((i + 1) / len(imgs), desc=f"DepthFlow {i+1}/{len(imgs)} · {stem}")
        if os.path.exists(out):                          # resume: bỏ qua clip đã có
            skipped += 1; continue
        if depthflow_clip(im, dur, fps, out):
            made += 1
        else:
            failed += 1; fails.append(stem)
    msg = (f"✅ Parallax clips: tạo {made}, bỏ qua {skipped}, lỗi {failed} · "
           f"{time.time()-t0:.0f}s\nOutput: {out_dir}\n"
           f"→ Tải folder Parallax/ về, up cạnh folder asset rồi chạy `/parallax-video` ở local.")
    if fails:
        msg += ("\n⚠️ Ảnh lỗi: " + ", ".join(fails[:10]) +
                "\nChạy `!depthflow --help` để xem cú pháp rồi sửa depthflow_clip().")
    return msg


with gr.Blocks(title="VideoTool V4 — DepthFlow clips-only") as demo:
    gr.Markdown("## V4 · DepthFlow — sinh clip parallax 2.5D (chỉ clip, không ghép)\n"
                "Nhập path/URL folder Drive chứa `Image/`. Output → `Parallax/<tên-ảnh>.mp4` "
                "(loopable). Tải về, up cạnh asset, rồi `/parallax-video` ở local.")
    inp = gr.Textbox(label="Folder asset (Drive path hoặc URL)", value="/content/drive/MyDrive/")
    dur = gr.Slider(8, 12, 10, step=1, label="Độ dài clip (giây, loopable)")
    fp = gr.Slider(24, 30, 30, step=1, label="FPS")
    btn = gr.Button("Render clips", variant="primary")
    log = gr.Textbox(label="Log")
    btn.click(make_clips, [inp, dur, fp], [log])

demo.launch(share=True, debug=True)
