import os
import subprocess
import threading
import traceback

from haillo.voice import player as p


class Voice:
    SAMPLE_RATE = 22050
    CHANNELS = 1
    PCM_CHUNK_SIZE = 4096

    def __init__(self):
        self.player = p.AudioPlayer()

        self._lock = threading.RLock()
        self._thread = None
        self._cancel = None
        self._process = None
        self._generation = 0
        self._is_enabled = False

    def speak(self, message):
        if not message:
            return

        self.stop()

        cancel = threading.Event()

        with self._lock:
            self._generation += 1
            generation = self._generation
            self._cancel = cancel

            thread = threading.Thread(
                target=self._speak_worker,
                args=(message, cancel, generation),
                name="hai-voice",
                daemon=True,
            )

            self._thread = thread

        thread.start()

    def _speak_worker(self, message, cancel, generation):
        process = None
        player_started = False
        completed = False

        try:
            # Equivalent to:
            #
            #   echo "message" | hai voice
            #
            process = subprocess.Popen(
                ["hai", "voice"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                bufsize=0,
            )

            with self._lock:
                if self._generation != generation:
                    self._terminate_process(process)
                    return

                self._process = process

            # Send the request to hai voice.
            process.stdin.write(message.encode("utf-8") + b"\n")
            process.stdin.close()

            # hai voice emits raw signed 16-bit, mono PCM at 22050 Hz.
            self.player.start(sample_rate=self.SAMPLE_RATE, channels=self.CHANNELS)
            player_started = True

            stdout_fd = process.stdout.fileno()

            while not cancel.is_set():
                if not self._is_current(generation):
                    break

                # os.read() returns data as it becomes available. This is
                # preferable here to waiting for a complete buffered read.
                pcm_data = os.read(stdout_fd, self.PCM_CHUNK_SIZE)

                if not pcm_data:
                    break

                if cancel.is_set() or not self._is_current(generation):
                    break

                self.player.feed(pcm_data)

            return_code = process.wait()

            if (return_code == 0 and not cancel.is_set() and self._is_current(generation)):
                # Tell AudioPlayer that the PCM stream is complete. It will
                # drain queued audio before ending and restoring ducked audio.
                self.player.finish()
                completed = True

        except BrokenPipeError:
            # hai voice exited before its stdin was fully written.
            pass

        except OSError:
            # Usually caused by cancellation/termination while reading stdout.
            if not cancel.is_set():
                traceback.print_exc()

        except Exception:
            traceback.print_exc()

        finally:
            if process is not None:
                self._terminate_process(process)

            # On cancellation, failure, or replacement, stop playback.
            # Do not stop it after successful finish(), because AudioPlayer
            # must drain its remaining queued PCM.
            if (player_started and not completed and self._is_current(generation)):
                self.player.stop()

            with self._lock:
                if self._process is process:
                    self._process = None

                if self._generation == generation:
                    self._thread = None
                    self._cancel = None

    def _terminate_process(self, process):
        if process.poll() is not None:
            return

        try:
            process.terminate()
            process.wait(timeout=0.5)
        except subprocess.TimeoutExpired:
            try:
                process.kill()
                process.wait()
            except OSError:
                pass
        except OSError:
            pass

    def _is_current(self, generation):
        with self._lock:
            return self._generation == generation

    def stop(self):
        with self._lock:
            self._generation += 1

            cancel = self._cancel
            thread = self._thread
            process = self._process

            self._cancel = None
            self._thread = None
            self._process = None

        if cancel is not None:
            cancel.set()

        # Terminating the producer causes os.read() to return or fail.
        if process is not None:
            self._terminate_process(process)

        # Stop and restore the AudioDucker through AudioPlayer.
        self.player.stop()

        if (thread is not None and thread is not threading.current_thread()):
            thread.join(timeout=0.5)

    def pause(self):
        self.player.pause()

    def resume(self):
        self.player.resume()

    def is_speaking(self):
        return self.player.is_speaking()

    def is_paused(self):
        return self.player.is_paused()

    def is_enabled(self):
        return self._is_enabled

    def set_enabled(self, enabled):
        self._is_enabled = enabled

    def toggle_voice(self):
        if self._is_enabled:
            self._is_enabled = False
        else:
            self._is_enabled = True

        return self._is_enabled
