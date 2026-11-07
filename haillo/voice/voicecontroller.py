import os
import traceback
import subprocess
import threading
import config

from huckle import cli, stdin
from haillo.voice import voice as v


class VoiceController():

    def __init__(self):
        self.voice = v.Voice()
        self.voice_lock = threading.Lock()
        self.voice_spawn_window = None
        self.current_window = None

    def toggle_voice(self) -> bool:

        enabled = False
        try:
            enabled = self.voice.toggle_voice()
        except Exception:
            return False

        try:
            if enabled:
                self.terminate_spawn_voice()
                self.spawn_voice()
            else:
                self.terminate_spawn_voice()
        except OSError:
            return False
        except Exception:
            pass

        return True

    def pause_voice(self) -> None:
        try:
            self.voice.pause()
        except Exception:
            pass

    def resume_voice(self) -> None:
        try:
            self.voice.resume()
        except Exception:
            pass

    def stream_voice(self, summary_id) -> bool:
        if self.voice.is_enabled():
            message = None
            try:
                chunks = cli("hai summary pull " + summary_id)
                message = b"".join(c for d, c in chunks if d == "stdout").decode('utf-8').strip()
            except Exception:
                traceback.print_exc()
                return False

            try:
                if message:
                    self.voice.speak(message)
            except OSError:
                return False
            except Exception:
                pass

            return True

    def voice_tag_active(self) -> Optional[bool]:
        """
        Return whether a client with the voice tag exists.

        True  = voice window exists
        False = voice window does not exist
        None  = unable to determine state
        """
        try:
            result = subprocess.run(
                ["hyprctl", "clients", "-j"],
                env=os.environ,
                capture_output=True,
                text=True,
                check=False,
            )

            if result.returncode != 0:
                return None

            clients = json.loads(result.stdout)

            for client in clients:
                tags = client.get("tags", [])
                if "hai-voice-assistant" in tags:
                    return True

            return False

        except (OSError, ValueError, TypeError):
            return None

    def spawn_voice(self) -> None:
        with self.voice_lock:
            try:
                # capture current window, launch, tag, restore focus
                # (identical body to the original, minus the tag check)
                result = subprocess.run(
                    ["hyprctl", "repl",
                     "string.format('address:0x%x', hl.get_active_window().address)"],
                    env=os.environ, capture_output=True, text=True, check=False,
                )
                self.current_window = result.stdout.strip()
                subprocess.run(
                    ["/bin/bash", config.voice],
                    env=os.environ, capture_output=True, text=True, check=False,
                )
                result = subprocess.run(
                    ["hyprctl", "repl",
                     "string.format('address:0x%x', hl.get_active_window().address)"],
                    env=os.environ, capture_output=True, text=True, check=False,
                )
                self.voice_spawn_window = result.stdout.strip()
                subprocess.run(
                    ["hyprctl", "dispatch",
                     f'hl.dsp.window.tag({{ tag = "+hai-voice-assistant", window = "{self.voice_spawn_window}" }})'],
                    env=os.environ, capture_output=True, text=True, check=False,
                )
                subprocess.run(
                    ["hyprctl", "dispatch",
                     f'hl.dsp.focus({{ window = "{self.current_window}" }})'],
                    env=os.environ, capture_output=True, text=True, check=False,
                )
            except Exception:
                pass

    def terminate_spawn_voice(self, force: bool = False) -> None:
        with self.voice_lock:
            try:
                subprocess.run(
                    ["hyprctl", "dispatch",
                     'hl.dsp.window.close({ window = "tag:hai-voice-assistant" })'],
                    env=os.environ, capture_output=True, text=True, check=False,
                )
            except OSError:
                pass
            finally:
                self.voice_spawn_window = None
                self.voice.stop()
