import io
import queue
import threading
import traceback
import wave

import numpy as np
import sounddevice as sd
import logger

from haillo.voice import audioducker as a


log = logger.Logger()


class AudioPlayer:
    _WRITE_FRAMES = 1024

    def __init__(self):
        self._lock = threading.RLock()

        self._thread = None
        self._stream = None
        self._ducker = None

        self._queue = queue.Queue()
        self._stop_event = threading.Event()
        self._done = threading.Event()
        self._done.set()

        self._pause_requested = threading.Event()
        self._resume_event = threading.Event()
        self._resume_event.set()

        self._sample_rate = None
        self._channels = None

    def start(self, sample_rate, channels=1):
        """
        Start receiving and playing a streamed PCM audio response.

        PCM must be:
            signed int16
            native endian
            mono or interleaved multi-channel
        """

        self.stop()

        with self._lock:
            self._sample_rate = sample_rate
            self._channels = channels

            self._stop_event.clear()
            self._done.clear()

            self._pause_requested.clear()
            self._resume_event.set()

            # Replace any stale data or completion marker.
            self._queue = queue.Queue()

            self._thread = threading.Thread(
                target=self._worker,
                name="hai-audio-player",
                daemon=True,
            )

            thread = self._thread

        thread.start()

    def feed(self, pcm_data):
        """
        Queue one raw PCM chunk for playback.

        This method is called as binary audio chunks arrive from the
        server.
        """

        if not pcm_data:
            return

        with self._lock:
            if self._stop_event.is_set():
                return

        self._queue.put(pcm_data)

    def finish(self):
        """
        Tell the player that no more PCM chunks will arrive.
        """

        self._queue.put(None)

    def play(self, wav_data):
        """
        Compatibility method for complete WAV data.

        This preserves the old style of usage:

            player.play(wav_bytes)

        For streaming server audio, use start(), feed(), and finish()
        instead.
        """

        audio, sample_rate, channels = self._decode_wav(wav_data)

        self.start(
            sample_rate=sample_rate,
            channels=channels,
        )

        for offset in range(0, len(audio), self._WRITE_FRAMES):
            if self._stop_event.is_set():
                break

            chunk = audio[offset:offset + self._WRITE_FRAMES]

            if not chunk.flags.c_contiguous:
                chunk = np.ascontiguousarray(chunk)

            self.feed(chunk.tobytes())

        self.finish()

    def pause(self):
        with self._lock:
            active = (
                self._thread is not None
                and not self._done.is_set()
            )

        if active:
            self._pause_requested.set()
            self._resume_event.clear()

    def resume(self):
        self._pause_requested.clear()
        self._resume_event.set()

    def stop(self, wait=True, timeout=2.0):
        with self._lock:
            thread = self._thread

            self._stop_event.set()
            self._pause_requested.clear()
            self._resume_event.set()

        # Wake the worker if it is blocked waiting for PCM.
        self._queue.put(None)

        if not wait:
            return

        if (
            thread is None
            or thread is threading.current_thread()
        ):
            return

        self._done.wait(timeout=timeout)

        if thread.is_alive():
            log.debug(
                "Audio player thread did not stop within timeout"
            )

    def wait(self, timeout=None):
        self._done.wait(timeout=timeout)

    def is_speaking(self):
        return not self._done.is_set()

    def is_paused(self):
        return (
            self._pause_requested.is_set()
            and self.is_speaking()
        )

    def _worker(self):
        stream = None
        ducker = None

        try:
            with self._lock:
                sample_rate = self._sample_rate
                channels = self._channels

            ducker = a.AudioDucker(
                duck_to=0.25,
                fade_s=0.8,
                fade_steps=20,
            )
            ducker.__enter__()

            stream = sd.RawOutputStream(
                samplerate=sample_rate,
                channels=channels,
                dtype="int16",
                blocksize=self._WRITE_FRAMES,
            )

            with self._lock:
                self._stream = stream

            stream.start()

            while not self._stop_event.is_set():
                pcm_data = self._queue.get()

                # None means either finish() or stop().
                if pcm_data is None:
                    break

                if not self._wait_if_paused():
                    break

                if self._stop_event.is_set():
                    break

                stream.write(pcm_data)

        except sd.PortAudioError:
            log.debug("port audio error; playback terminated")

        except Exception:
            log.error(traceback.format_exc())

        finally:
            if stream is not None:
                try:
                    if getattr(stream, "active", False):
                        stream.stop()
                except Exception:
                    pass

                try:
                    stream.close()
                except Exception:
                    pass

            if ducker is not None:
                try:
                    ducker.__exit__(None, None, None)
                except Exception:
                    pass

            with self._lock:
                if self._stream is stream:
                    self._stream = None

                if self._thread is threading.current_thread():
                    self._thread = None

            self._done.set()
            a.AudioDucker.restore_foreign_to_full()

    def _wait_if_paused(self):
        while self._pause_requested.is_set():
            if self._stop_event.is_set():
                return False

            self._resume_event.wait(timeout=0.1)

        return not self._stop_event.is_set()

    def _decode_wav(self, wav_data):
        if hasattr(wav_data, "read"):
            source = wav_data
        else:
            source = io.BytesIO(wav_data)

        with wave.open(source, "rb") as wav:
            channels = wav.getnchannels()
            sample_width = wav.getsampwidth()
            sample_rate = wav.getframerate()
            frames = wav.readframes(wav.getnframes())

        if sample_width != 2:
            raise ValueError(
                "Only signed 16-bit PCM WAV is supported"
            )

        audio = np.frombuffer(
            frames,
            dtype=np.int16,
        )

        if channels > 1:
            audio = audio.reshape(-1, channels)

        return audio, sample_rate, channels
