# @title VideoTool Colab/Kaggle — Qi-wisps atmosphere overlay (GPU GLSL) → qi-gen-01.mp4
# =====================================================================
# DÁN TOÀN BỘ block này vào MỘT cell (Colab hoặc Kaggle), bật GPU, rồi Run.
# Sinh 1 overlay "linh khí" (qi wisps): tua/sợi sáng lam-lục cuộn theo flow-field, nền ĐEN,
# loop LIỀN MẠCH ~18s. Tải về, đặt vào ~/.local/share/videotool/overlays/qi-gen-01.mp4 ở local;
# pipeline tiêu thụ qua inputs.particle_overlay + enhance.atmosphere (screen-blend) như mọi clip.
#
# Vì sao GLSL/Colab chứ không Three.js/Remotion: headless WebGL trên Colab hay rơi SwiftShader
# (CPU). moderngl + EGL (cùng mẹo libnvidia-gl + ICD như v4_depthflow) chạm GPU NVIDIA thật.
# Linh khí (flow-field) là hiệu ứng DUY NHẤT GPU thắng rõ so với numpy point-sprite (3 preset
# kia sinh local bằng scripts/gen_overlay.py).
#
# Seamless loop: mọi chuyển động của field là hàm của cos(2π·t)/sin(2π·t) → frame0 == frameN.
# =====================================================================
import json, os, shutil, subprocess, sys

# ---- môi trường: Colab hay Kaggle (cả hai NVIDIA headless Linux) -------------------
IS_KAGGLE = os.path.exists("/kaggle")
try:
    import google.colab  # noqa: F401
    IS_COLAB = True
except Exception:
    IS_COLAB = False

OUT_DIR = "/kaggle/working" if IS_KAGGLE else "/content"
os.makedirs(OUT_DIR, exist_ok=True)
OUT_PATH = f"{OUT_DIR}/qi-gen-01.mp4"

# Tham số overlay (đổi nếu cần)
WIDTH, HEIGHT, FPS, SECONDS = 1920, 1080, 30, 18
COLOR = (0.42, 0.86, 0.74)   # lam-lục linh khí
DENSITY = 0.66               # ngưỡng mật độ tua sáng (cao = thưa hơn, linh khí mỏng)
BRIGHTNESS = 0.9             # độ sáng tua (thấp = phiêu nhẹ, chìm vào nền)


def sh(cmd, check=True):
    print("+", cmd)
    return subprocess.run(cmd, shell=True, check=check)


sh("apt-get -qq install -y ffmpeg >/dev/null 2>&1 || true", check=False)
sh("pip -q install moderngl numpy pillow", check=False)


def setup_nvidia_egl():
    """Driver Colab/Kaggle chỉ có CUDA compute, thiếu userspace EGL của NVIDIA → moderngl rơi
    llvmpipe (CPU). Cài libnvidia-gl khớp major + đăng ký ICD 10_nvidia (10_ < 50_mesa → EGL ưu
    tiên NVIDIA). Pattern giống Colab/v4_depthflow_clips_colab.py."""
    if not shutil.which("nvidia-smi"):
        print("⚠️ Không thấy GPU. Bật GPU runtime (Colab: Runtime>GPU; Kaggle: Settings>Accelerator).")
        return
    ver = subprocess.run("nvidia-smi --query-gpu=driver_version --format=csv,noheader",
                         shell=True, capture_output=True, text=True).stdout.strip()
    major = ver.split(".")[0] if ver else ""
    if major:
        sh(f"apt-get -qq install -y libnvidia-gl-{major} 2>&1 | tail -2", check=False)
    icd = "/usr/share/glvnd/egl_vendor.d/10_nvidia.json"
    if not os.path.exists(icd):
        os.makedirs(os.path.dirname(icd), exist_ok=True)
        with open(icd, "w") as f:
            json.dump({"file_format_version": "1.0.0",
                       "ICD": {"library_path": "libEGL_nvidia.so.0"}}, f)
    print(f"✅ NVIDIA EGL sẵn sàng (driver {ver}).")


setup_nvidia_egl()
# Hard-set (NOT setdefault): Colab may pre-seed MODERNGL_BACKEND empty/x11, and setdefault
# won't override it → glcontext falls back to the x11 backend → "XOpenDisplay: cannot open
# display" on headless. Force EGL before importing moderngl so it picks the NVIDIA EGL path.
os.environ["MODERNGL_BACKEND"] = "egl"
os.environ["PYOPENGL_PLATFORM"] = "egl"

import numpy as np
import moderngl

# Fullscreen-quad vertex shader.
VERT = """
#version 330
in vec2 in_pos;
out vec2 uv;
void main() { uv = in_pos * 0.5 + 0.5; gl_Position = vec4(in_pos, 0.0, 1.0); }
"""

# Fragment shader: value-noise FBM domain-warped by a PERIODIC flow → wispy tendrils on black.
# Time enters only via cos(TAU*t)/sin(TAU*t), so the field at t=0 equals t=1 (seamless loop).
FRAG = """
#version 330
in vec2 uv;
out vec4 frag;
uniform float u_t;        // loop phase 0..1
uniform vec2  u_res;
uniform vec3  u_color;
uniform float u_density;
uniform float u_bright;
const float TAU = 6.28318530718;

float hash(vec2 p){ p = fract(p*vec2(123.34, 345.45)); p += dot(p, p+34.345); return fract(p.x*p.y); }
float vnoise(vec2 p){
    vec2 i = floor(p), f = fract(p);
    vec2 u = f*f*(3.0-2.0*f);
    float a = hash(i), b = hash(i+vec2(1,0)), c = hash(i+vec2(0,1)), d = hash(i+vec2(1,1));
    return mix(mix(a,b,u.x), mix(c,d,u.x), u.y);
}
float fbm(vec2 p){
    float v = 0.0, amp = 0.5;
    for(int i=0;i<5;i++){ v += amp*vnoise(p); p *= 2.0; amp *= 0.5; }
    return v;
}
void main(){
    vec2 p = uv * vec2(u_res.x/u_res.y, 1.0) * 3.0;
    // Periodic flow: orbiting offsets at two scales (same period) keep the loop closed.
    vec2 f1 = vec2(cos(TAU*u_t), sin(TAU*u_t));
    vec2 f2 = vec2(cos(TAU*u_t + 1.7), sin(TAU*u_t + 1.7));
    vec2 warp = vec2(fbm(p + 0.6*f1), fbm(p + vec2(5.2) - 0.6*f1));
    float field = fbm(p + 1.8*warp + 0.5*f2);
    // Soft tendrils: emphasise a NARROW mid-band of the field, fade the rest to black. A thin band
    // = sparse, wispy threads (not a dense cloud) so the qi drifts lightly over the scene.
    float wisp = smoothstep(u_density, u_density+0.07, field) * (1.0 - smoothstep(u_density+0.07, u_density+0.22, field));
    vec3 col = u_color * wisp * u_bright;
    frag = vec4(col, 1.0);
}
"""


def make_context():
    """Colab's bundled glcontext IGNORES the MODERNGL_BACKEND env var — it only honours the
    `backend=` kwarg passed straight through create_context. Without it, standalone mode on Linux
    defaults to the x11 backend → "XOpenDisplay: cannot open display" on headless. So request EGL
    explicitly (touches the NVIDIA GPU via the ICD set up above). If EGL is unavailable for any
    reason, fall back to a virtual X display (xvfb) so the render still completes on CPU (llvmpipe)
    — the GLSL output is identical, only slower."""
    try:
        ctx = moderngl.create_context(standalone=True, backend="egl")
        print("EGL context OK.")
        return ctx
    except Exception as e:
        print("⚠️ EGL backend failed (", e, ") → falling back to xvfb + CPU render.")
        sh("apt-get -qq install -y xvfb >/dev/null 2>&1 || true", check=False)
        sh("pip -q install pyvirtualdisplay", check=False)
        from pyvirtualdisplay import Display
        Display(visible=0, size=(WIDTH, HEIGHT)).start()
        return moderngl.create_context(standalone=True)  # x11 against the virtual display


def main():
    ctx = make_context()
    print("GL renderer:", ctx.info.get("GL_RENDERER", "?"),
          "→", "GPU OK" if "llvmpipe" not in ctx.info.get("GL_RENDERER", "").lower() else "⚠️ CPU llvmpipe (slower, output identical)")
    prog = ctx.program(vertex_shader=VERT, fragment_shader=FRAG)
    quad = ctx.buffer(np.array([-1,-1, 1,-1, -1,1, 1,1], dtype="f4").tobytes())
    vao = ctx.vertex_array(prog, [(quad, "2f", "in_pos")])
    fbo = ctx.framebuffer(color_attachments=[ctx.texture((WIDTH, HEIGHT), 3)])
    fbo.use()
    prog["u_res"].value = (WIDTH, HEIGHT)
    prog["u_color"].value = COLOR
    prog["u_density"].value = DENSITY
    prog["u_bright"].value = BRIGHTNESS

    total = FPS * SECONDS
    ff = subprocess.Popen(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
         "-s", f"{WIDTH}x{HEIGHT}", "-r", str(FPS), "-i", "-", "-an",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", OUT_PATH],
        stdin=subprocess.PIPE,
    )
    try:
        for i in range(total):
            prog["u_t"].value = i / total
            vao.render(moderngl.TRIANGLE_STRIP)
            data = fbo.read(components=3)
            frame = np.frombuffer(data, dtype=np.uint8).reshape(HEIGHT, WIDTH, 3)
            ff.stdin.write(np.flipud(frame).tobytes())   # GL origin bottom-left → flip
    finally:
        ff.stdin.close()
        ff.wait()
    if ff.returncode != 0:
        raise RuntimeError("ffmpeg failed encoding qi-gen-01.mp4")
    print("wrote", OUT_PATH)


main()

# ---- tải về ----------------------------------------------------------------------
print("\n== TẢI VỀ ==")
print(f"File: {OUT_PATH}")
print("→ Đặt vào local: ~/.local/share/videotool/overlays/qi-gen-01.mp4")
if IS_COLAB:
    try:
        from google.colab import files
        files.download(OUT_PATH)
    except Exception as e:
        print("Tự tải từ panel Files. (", e, ")")
elif IS_KAGGLE:
    print("Kaggle: file nằm trong /kaggle/working → tab Output > Download.")
