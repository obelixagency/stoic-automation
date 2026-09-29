"""Generate copyright-free ambient beds procedurally (we own them: no licenses, no Content ID claims).
Each bed is a seamless 60 s loop: detuned sine pad on a minor chord + slow swells + periodic (FFT-synthesised) air noise."""
import numpy as np, subprocess, sys, os, wave
SR = 44100; LOOP = 60; N = SR * LOOP
def snap(f): return round(f * LOOP) / LOOP                   # integer cycles per loop -> perfectly seamless

def bed(root_hz, third=6 / 5, fifth=3 / 2, seed=0):
    rng = np.random.default_rng(seed); t = np.arange(N) / SR; L = np.zeros(N); R = np.zeros(N)
    notes = [root_hz / 2, root_hz, root_hz * third, root_hz * fifth, root_hz * 2, root_hz * 2 * third]
    for k, f0 in enumerate(notes):
        for det in (-0.9, 0.0, 0.9):                            # slight detune -> slow beating, warm
            f = snap(f0 * (1 + det / 1000)); ph = rng.uniform(0, 2 * np.pi, 2)
            swell = 0.6 + 0.4 * np.sin(2 * np.pi * (1 + k % 3) / LOOP * t + rng.uniform(0, 6.28))
            amp = 0.11 / (1 + 0.35 * k) * swell
            L += amp * np.sin(2 * np.pi * f * t + ph[0]); R += amp * np.sin(2 * np.pi * f * t + ph[1])
    spec = np.zeros(N // 2 + 1, complex); fr = np.fft.rfftfreq(N, 1 / SR)                # periodic air noise
    shape = np.where(fr > 40, 1 / np.maximum(fr, 40) ** 1.2, 0) * (fr < 1500)
    for ch, arr in enumerate((L, R)):
        sp = shape * np.exp(1j * rng.uniform(0, 2 * np.pi, len(fr))); n = np.fft.irfft(sp, N); n /= np.abs(n).max(); arr += 0.05 * n
    out = np.stack([L, R], 1); out *= 0.03 / np.sqrt((out ** 2).mean())   # quiet bed: about -31 LUFS, sits under a voice
    return np.clip(out, -1, 1)

def write(path_wav, data):
    with wave.open(path_wav, "wb") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR); w.writeframes((data * 32767).astype("<i2").tobytes())

if __name__ == "__main__":
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "music"); os.makedirs(out, exist_ok=True)
    for name, root in (("dusk_dm", 73.42 * 2), ("stone_am", 55.0 * 2), ("harbor_em", 82.41 * 2)):
        wav = f"/tmp/{name}.wav"; write(wav, bed(root, seed=hash(name) % 1000))
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", wav, "-c:a", "aac", "-b:a", "160k", f"{out}/{name}.m4a"], check=True); print("wrote", name)
