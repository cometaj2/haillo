#!/usr/bin/env python3
"""Radial ASCII spectrum, in the spirit of snglrtty.

A center ring plus frequency bars that pulse outward, drawn with ANSI
glyphs on a decay buffer. Supports two modes:

- Full-screen (original behavior) using the alternate screen.
- Mini overlay mode (new): draws a small pulsing indicator in the
  top-right corner of the terminal without disturbing the main content.
  Intended for use as a voice-assist indicator.

Audio comes from a Pulse/PipeWire monitor via ``parec`` (see ttyspec.sh),
from stdin float32le, or from a built-in demo.
"""

from __future__ import annotations

import argparse
import math
import os
import shutil
import signal
import struct
import subprocess
import sys
import time
from typing import Optional, Sequence

THEMES: dict[str, tuple[tuple[str, str], ...]] = {
    "default": (("37", "."), ("32", "#"), ("92", "+"), ("37", "*")),
    "fire":    (("33", "."), ("91", "#"), ("31", "+"), ("93", "*")),
    "ocean":   (("34", "."), ("94", "#"), ("37", "+"), ("96", "*")),
    "forest":  (("92", "."), ("32", "#"), ("32", "+"), ("90", "*")),
    "sun":     (("33", "."), ("93", "#"), ("37", "+"), ("90", "*")),
    "mono":    (("90", "."), ("37", "#"), ("37", "+"), ("90", "*")),
}

RATE = 44100
CHUNK = 512
LATENCY_MS = 20
BARS = 48
DECAY = 0.72
RADIUS = 6.0
BAR_SCALE = 7.0
F_HI = 8000.0

MINI_WIDTH = 5 # 14
MINI_HEIGHT = 3 # 9



# | Value | Effect | Recommendation |
# |-------|--------|----------------|
# | `2.6` | Current | Quite big for a mini overlay |
# | `2.0` | Moderately smaller | Good balance |
# | `1.7` | Quite small | Cleaner, less text interference |
# | `1.5` | Very small | Minimal footprint |
MINI_RADIUS = 0.1

def _winsize(fd: int) -> tuple[int, int]:
    try:
        import fcntl, termios
        packed = fcntl.ioctl(fd, termios.TIOCGWINSZ, b"\x00" * 8)
        rows, cols, _, _ = struct.unpack("HHHH", packed)
        return max(rows, 8), max(cols, 16)
    except (OSError, ImportError):
        size = shutil.get_terminal_size(fallback=(80, 24))
        return size.lines, size.columns


def _fft(samples: Sequence[float]) -> list[tuple[float, float]]:
    n = len(samples)
    if (n & (n - 1)) != 0:
        raise ValueError("FFT input length must be a power of two")
    re = list(samples)
    im = [0.0] * n
    j = 0
    for i in range(1, n):
        bit = n >> 1
        while j & bit:
            j ^= bit
            bit >>= 1
        j ^= bit
        if i < j:
            re[i], re[j] = re[j], re[i]
    length = 2
    while length <= n:
        ang = -2.0 * math.pi / length
        wre, wim = math.cos(ang), math.sin(ang)
        for i in range(0, n, length):
            wr, wi = 1.0, 0.0
            half = length >> 1
            for k in range(half):
                tr = wr * re[i + k + half] - wi * im[i + k + half]
                ti = wr * im[i + k + half] + wi * re[i + k + half]
                re[i + k + half] = re[i + k] - tr
                im[i + k + half] = im[i + k] - ti
                re[i + k] += tr
                im[i + k] += ti
                wr, wi = wr * wre - wi * wim, wr * wim + wi * wre
        length <<= 1
    return list(zip(re, im))


class RadialSpectrum:
    """Radial spectrum visualizer with optional mini overlay (top-right)."""

    def __init__(
        self,
        fd: int,
        theme: str = "default",
        bars: int = BARS,
        decay: float = DECAY,
        radius: float = RADIUS,
        ghost: bool = False,
        mode: str = "fft",
        sensitivity: float = 1.0,
        rate: int = RATE,
        mini: bool = False,
        mini_width: int = MINI_WIDTH,
        mini_height: int = MINI_HEIGHT,
    ) -> None:
        if theme not in THEMES:
            raise ValueError(f"unknown theme {theme!r}")
        if mode not in ("fft", "chunk"):
            raise ValueError("mode must be 'fft' or 'chunk'")

        self.fd = fd
        self.theme = theme
        self.mini = mini
        self.ghost = ghost
        self.mode = mode
        self.sensitivity = sensitivity
        self.rate = rate
        self.on = False

        if mini:
            self.bars = max(6, mini_width // 2)
            self.radius = MINI_RADIUS
            self._mini_w = mini_width
            self._mini_h = mini_height
            self._rows = mini_height
            self._cols = mini_width
            self._term_cols = 0
        else:
            self.bars = max(8, bars)
            self.radius = radius
            self._rows = 0
            self._cols = 0
            self._term_cols = 0

        self.decay = min(max(decay, 0.0), 0.99)
        self._buf: list[list[float]] = []
        self._pending = bytearray()
        self._window = [0.5 - 0.5 * math.cos(2 * math.pi * i / (CHUNK - 1)) for i in range(CHUNK)]
        self._edges = self._log_edges(self.bars, rate)
        self._peak = 0.05
        self._smooth = [0.0] * self.bars
        self._palette = self._compile(THEMES[theme])

    @staticmethod
    def _log_edges(n: int, rate: int) -> list[tuple[int, int]]:
        hi = min(F_HI, rate / 2 - 1)
        edges = []
        F_LO = 2.5
        for i in range(n):
            a = F_LO * (hi / F_LO) ** (i / n)
            b = F_LO * (hi / F_LO) ** ((i + 1) / n)
            i0 = max(1, int(a * CHUNK / rate))
            i1 = max(i0 + 1, int(b * CHUNK / rate))
            edges.append((i0, min(i1, CHUNK // 2)))
        return edges

    @staticmethod
    def _compile(glyphs: tuple[tuple[str, str], ...]) -> tuple[bytes, ...]:
        return tuple(f"\x1b[{code}m{ch}\x1b[0m".encode() for code, ch in glyphs)

    def start(self) -> None:
        if self.on:
            return
        if not self.mini:
            try:
                os.write(self.fd, b"\x1b[?1049h\x1b[?25l\x1b[H\x1b[2J")
            except OSError:
                return
        else:
            try:
                os.write(self.fd, b"\x1b[?25l")
            except OSError:
                pass
        self.on = True
        if not self.mini:
            self._resize(force=True)
        else:
            self._buf = [[0.0] * self._mini_w for _ in range(self._mini_h)]
            self._update_term_width()

    def clear(self) -> None:
        if not self.on:
            return
        if self.mini:
            self._clear_mini_region()
            try:
                os.write(self.fd, b"\x1b[?25h")
            except OSError:
                pass
        else:
            try:
                os.write(self.fd, b"\x1b[0m\x1b[?25h\x1b[?1049l")
            except OSError:
                pass
        self.on = False

    def _update_term_width(self) -> None:
        try:
            _, cols = _winsize(self.fd)
            self._term_cols = cols
        except Exception:
            self._term_cols = 80

    def _clear_mini_region(self) -> None:
        if not self.mini:
            return
        self._update_term_width()
        start_col = max(1, self._term_cols - self._mini_w + 1)
        try:
            os.write(self.fd, b"\x1b[s")
            for y in range(self._mini_h):
                os.write(self.fd, f"\x1b[{y + 1};{start_col}H".encode())
                os.write(self.fd, b" " * self._mini_w)
            os.write(self.fd, b"\x1b[u")
        except OSError:
            pass

    def push(self, samples: Sequence[float]) -> None:
        self._pending.extend(struct.pack(f"<{len(samples)}f", *samples))

    def push_bytes(self, raw: bytes) -> None:
        self._pending.extend(raw)
        keep = CHUNK * 4
        if len(self._pending) > keep:
            del self._pending[:-keep]

    def tick(self) -> None:
        if not self.on:
            self.start()
        if not self.mini:
            self._resize()
        else:
            self._update_term_width()
        self._decay()
        samples = self._take()
        if samples is not None:
            amps = self._bands(samples)
            self._stamp(amps)
        self._paint()

    def _resize(self, force: bool = False) -> None:
        if self.mini:
            return
        rows, cols = _winsize(self.fd if os.isatty(self.fd) else sys.stdout.fileno())
        if not force and rows == self._rows and cols == self._cols:
            return
        self._rows, self._cols = rows, cols
        self._buf = [[0.0] * cols for _ in range(rows)]

    def _decay(self) -> None:
        d = self.decay
        buf = self._buf
        for y in range(self._rows):
            row = buf[y]
            for x in range(self._cols):
                row[x] *= d

    def _take(self) -> Optional[list[float]]:
        need = CHUNK * 4
        if len(self._pending) < need:
            return None
        raw = bytes(self._pending[:need])
        del self._pending[:need]
        return list(struct.unpack(f"<{CHUNK}f", raw))

    def _bands(self, samples: Sequence[float]) -> list[float]:
        if self.mode == "chunk":
            return self._chunk_bands(samples)
        return self._fft_bands(samples)

    def _chunk_bands(self, samples: Sequence[float]) -> list[float]:
        n = self.bars
        step = max(1, len(samples) // n)
        out = []
        for i in range(n):
            chunk = samples[i * step : (i + 1) * step] or samples[-1:]
            out.append(sum(abs(s) for s in chunk) / len(chunk))
        return out

    def _fft_bands(self, samples: Sequence[float]) -> list[float]:
        windowed = [samples[i] * self._window[i] for i in range(CHUNK)]
        spec = _fft(windowed)
        scale = 2.0 / CHUNK
        out = []
        for i0, i1 in self._edges:
            acc = 0.0
            for k in range(i0, i1):
                re, im = spec[k]
                acc += re * re + im * im
            out.append(math.sqrt(acc / max(1, i1 - i0)) * scale)
        return out

    def _stamp(self, amps: list[float]) -> None:
        rows = self._rows
        cols = self._cols
        buf = self._buf
        cx = cols / 2.0
        cy = rows / 2.0
        radius = self.radius
        n = len(amps)
        if n != len(self._smooth):
            self._smooth = [0.0] * n

        for i, amp in enumerate(amps):
            prev = self._smooth[i]
            self._smooth[i] = amp if amp > prev else prev * 0.82 + amp * 0.18
        blurred = [0.0] * n
        for i in range(n):
            blurred[i] = (
                self._smooth[(i - 1) % n] * 0.22
                + self._smooth[i] * 0.56
                + self._smooth[(i + 1) % n] * 0.22
            )

        peak = max(blurred) if blurred else 0.0
        self._peak = max(peak, self._peak * 0.99, 1e-4)
        reach = BAR_SCALE * self.sensitivity

        if not self.ghost:
            for i in range(360):
                ang = i / 360.0 * 2.0 * math.pi
                x = int(cx + radius * math.cos(ang) * 2.0)
                y = int(cy + radius * math.sin(ang))
                if 0 <= y < rows and 0 <= x < cols:
                    buf[y][x] = max(buf[y][x], 1.0)

        for i, amp in enumerate(blurred):
            shaped = math.sqrt(max(amp, 0.0) / self._peak)
            length = max(1, int(shaped * reach)) if shaped > 0.08 else 0
            if length == 0:
                continue
            for mirror in (0.0, math.pi):
                ang = mirror + (i + 0.5) / n * math.pi
                c = math.cos(ang)
                s = math.sin(ang)
                for step in range(length):
                    t = step / length
                    level = 1.0 - 0.55 * t
                    r = radius + 0.85 * step
                    x = int(cx + r * c * 2.0)
                    y = int(cy + r * s)
                    if 0 <= y < rows and 0 <= x < cols:
                        buf[y][x] = max(buf[y][x], level)
                    x2 = int(cx + r * c * 2.0 + (-s if i % 2 else s))
                    y2 = int(cy + r * s + (c if i % 2 else -c) * 0.4)
                    if 0 <= y2 < rows and 0 <= x2 < cols:
                        buf[y2][x2] = max(buf[y2][x2], level * 0.65)

    def _paint(self) -> None:
        high, mid_high, mid, low = self._palette
        buf = self._buf

        if self.mini:
            self._update_term_width()
            start_col = max(1, self._term_cols - self._mini_w + 1)
            try:
                os.write(self.fd, b"\x1b[s")
                for y in range(self._mini_h):
                    os.write(self.fd, f"\x1b[{y + 1};{start_col}H".encode())
                    line = bytearray()
                    for v in buf[y]:
                        if v > 0.8:
                            line += high
                        elif v > 0.6:
                            line += mid_high
                        elif v > 0.4:
                            line += mid
                        elif v > 0.2:
                            line += low
                        else:
                            line += b" "
                    os.write(self.fd, bytes(line))
                os.write(self.fd, b"\x1b[u")
            except OSError:
                pass
        else:
            parts = [b"\x1b[H"]
            for y in range(self._rows):
                row = buf[y]
                line = bytearray()
                for v in row:
                    if v > 0.8:
                        line += high
                    elif v > 0.6:
                        line += mid_high
                    elif v > 0.4:
                        line += mid
                    elif v > 0.2:
                        line += low
                    else:
                        line += b" "
                parts.append(bytes(line))
                if y + 1 < self._rows:
                    parts.append(b"\r\n")
            try:
                os.write(self.fd, b"".join(parts))
            except OSError:
                pass


def _monitor_source() -> str:
    sink = subprocess.check_output(["pactl", "get-default-sink"], text=True).strip()
    return f"{sink}.monitor"


def _spawn_parec(source: str, latency_ms: int) -> subprocess.Popen:
    env = os.environ.copy()
    env["PULSE_LATENCY_MSEC"] = str(latency_ms)
    return subprocess.Popen(
        ["parec", f"--device={source}", "--format=float32le",
         "--rate", str(RATE), "--channels=1",
         f"--latency-msec={latency_ms}"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env
    )


def _demo_samples(n: int, t0: float) -> list[float]:
    out = []
    for i in range(n):
        t = t0 + i / RATE
        v = (0.45 * math.sin(2 * math.pi * 220 * t) +
             0.30 * math.sin(2 * math.pi * 440 * t) +
             0.20 * math.sin(2 * math.pi * (880 + 40 * math.sin(t)) * t))
        out.append(v * (0.6 + 0.4 * math.sin(2 * math.pi * 2 * t)))
    return out


def run(spec: RadialSpectrum, source: str, latency_ms: int = LATENCY_MS) -> int:
    spec.start()
    proc: Optional[subprocess.Popen] = None
    t0 = 0.0
    stop = False

    def _stop(_signum, _frame):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    try:
        if source == "stdin":
            fd = sys.stdin.fileno()
            os.set_blocking(fd, False)
            while not stop:
                try:
                    raw = os.read(fd, 65536)
                except BlockingIOError:
                    raw = b""
                else:
                    if not raw:
                        break
                if raw:
                    spec.push_bytes(raw)
                    spec.tick()
                    continue
                if spec._pending:
                    spec.tick()
                time.sleep(0.004)

        elif source == "demo":
            period = CHUNK / RATE
            next_at = time.monotonic()
            while not stop:
                spec.push(_demo_samples(CHUNK, t0))
                t0 += period
                spec.tick()
                next_at += period
                delay = next_at - time.monotonic()
                if delay > 0:
                    time.sleep(delay)

        else:
            device = _monitor_source() if source == "monitor" else source
            proc = _spawn_parec(device, latency_ms)
            assert proc.stdout is not None
            fd = proc.stdout.fileno()
            os.set_blocking(fd, False)
            while not stop:
                try:
                    raw = os.read(fd, 65536)
                except BlockingIOError:
                    raw = b""
                if raw:
                    spec.push_bytes(raw)
                    spec.tick()
                    continue
                if proc.poll() is not None and not spec._pending:
                    break
                spec.tick()
                time.sleep(0.004)
    finally:
        spec.clear()
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                proc.kill()
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("-t", "--theme", default="default", choices=sorted(THEMES))
    p.add_argument("-b", "--bars", type=int, default=BARS)
    p.add_argument("-d", "--decay", type=float, default=DECAY)
    p.add_argument("-r", "--radius", type=float, default=RADIUS)
    p.add_argument("-g", "--ghost", action="store_true")
    p.add_argument("--mode", default="fft", choices=("fft", "chunk"))
    p.add_argument("--sensitivity", type=float, default=1.0)
    p.add_argument("--latency", type=int, default=LATENCY_MS)
    p.add_argument("--source", default="monitor")
    p.add_argument("--stdin", action="store_true")
    p.add_argument("--mini", action="store_true")
    p.add_argument("--mini-width", type=int, default=MINI_WIDTH)
    p.add_argument("--mini-height", type=int, default=MINI_HEIGHT)
    args = p.parse_args(argv)
    source = "stdin" if args.stdin else args.source
    spec = RadialSpectrum(
        sys.stdout.fileno(),
        theme=args.theme, bars=args.bars, decay=args.decay,
        radius=args.radius, ghost=args.ghost, mode=args.mode,
        sensitivity=args.sensitivity, mini=args.mini,
        mini_width=args.mini_width, mini_height=args.mini_height,
    )
    return run(spec, source, args.latency)


if __name__ == "__main__":
    raise SystemExit(main())
