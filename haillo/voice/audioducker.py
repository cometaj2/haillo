import sys
import time
import threading
import logger
import os

log = logger.Logger()


# Lower other apps' playback while TTS speaks.
# Linux (PipeWire/Pulse) only. Other platforms are a no-op so the
# same context-manager call site works everywhere.
class AudioDucker:
    FULL_VOLUME = 1.0
    _restore_lock = threading.Lock()

    def __init__(
        self,
        duck_to=0.25,
        exclude_pids=None,
        fade_s=0.4,
        fade_steps=10,
    ):
        self.duck_to = max(0.0, min(1.0, float(duck_to)))
        self.fade_s = max(0.0, float(fade_s))
        self.fade_steps = max(1, int(fade_steps))
        self.exclude_pids = {
            int(p)
            for p in (
                exclude_pids
                if exclude_pids is not None
                else [os.getpid()]
            )
        }
        self._saved = {}
        self._targets = []
        self._known = set()
        self._lock = threading.Lock()

    def __enter__(self):
        self._snapshot_and_duck()
        return self

    def __exit__(self, exc_type, exc, tb):
        self._restore()
        return False

    def _snapshot_and_duck(self):
        if sys.platform.startswith("linux"):
            self._linux_duck()

    def _restore(self):
        if sys.platform.startswith("linux"):
            self._linux_restore()

    def _linux_pulse(self):
        try:
            import pulsectl
        except ImportError:
            log.warning(
                "pulsectl not installed; audio ducking disabled"
            )
            return None

        try:
            return pulsectl.Pulse("hai-ducker")
        except Exception as e:
            log.warning(
                "pulse/pipewire unavailable; audio ducking disabled: %s",
                e,
            )
            return None

    def _proplist(self, si):
        return getattr(si, "proplist", None) or {}

    def _sink_pid(self, si):
        props = self._proplist(si)

        for key in (
            "application.process.id",
            "pipewire.pid",
        ):
            raw = props.get(key)
            if raw:
                try:
                    return int(raw)
                except (TypeError, ValueError):
                    pass

        return None

    def _is_ours(self, si, extra_pids=None):
        pids = set(self.exclude_pids)

        if extra_pids:
            pids.update(extra_pids)

        pid = self._sink_pid(si)
        return pid is not None and pid in pids

    def _target_key(self, si):
        props = self._proplist(si)

        return (
            si.index,
            props.get("application.process.id"),
            props.get("application.name"),
            props.get("media.name"),
        )

    def _matches_target(self, si, target):
        if si.index == target["index"]:
            return True

        props = self._proplist(si)

        if target.get("pid"):
            if props.get("application.process.id") == target["pid"]:
                if (
                    not target.get("app")
                    or props.get("application.name") == target["app"]
                ):
                    return True

        if target.get("app") and target.get("media"):
            if (
                props.get("application.name") == target["app"]
                and props.get("media.name") == target["media"]
            ):
                return True

        return False

    def _set_volume(self, pulse, si, vol):
        try:
            pulse.volume_set_all_chans(si, vol)
            return True
        except Exception as e:
            log.debug(
                "volume set failed for sink-input %s: %s",
                si.index,
                e,
            )
            return False

    # Duck foreign sink-inputs that appeared after the initial snapshot.
    # Sink-inputs belonging to this process are left at full volume.
    def protect_new(self):
        if not sys.platform.startswith("linux"):
            return

        pulse = self._linux_pulse()
        if pulse is None:
            return

        try:
            with self._lock:
                known = set(self._known)
                targets = list(self._targets)
                saved = dict(self._saved)

            live = list(pulse.sink_input_list())
            new_known = set(known)

            for si in live:
                if si.index in known:
                    continue

                new_known.add(si.index)

                if getattr(si, "mute", False):
                    continue

                if self._is_ours(si):
                    try:
                        pulse.volume_set_all_chans(
                            si,
                            self.FULL_VOLUME,
                        )
                        log.debug(
                            "left TTS stream %s at full volume",
                            si.index,
                        )
                    except Exception as e:
                        log.debug(
                            "could not protect sink-input %s: %s",
                            si.index,
                            e,
                        )
                    continue

                try:
                    original = si.volume.value_flat
                except Exception:
                    continue

                if original <= self.duck_to:
                    continue

                if not self._set_volume(
                    pulse,
                    si,
                    self.duck_to,
                ):
                    continue

                props = self._proplist(si)
                target = {
                    "index": si.index,
                    "pid": props.get("application.process.id"),
                    "app": props.get("application.name"),
                    "media": props.get("media.name"),
                    "start": original,
                }

                targets.append(target)
                saved[si.index] = original

            with self._lock:
                self._known.update(new_known)
                self._targets = targets
                self._saved = saved

        except Exception as e:
            log.debug("protect_new failed: %s", e)

        finally:
            try:
                pulse.close()
            except Exception:
                pass

    def _ramp(self, pulse, items, toward_full):
        if not items:
            return

        steps = self.fade_steps
        interval = self.fade_s / steps if steps else 0

        for i in range(1, steps + 1):
            t = i / float(steps)

            try:
                live = list(pulse.sink_input_list())
            except Exception:
                break

            for item in items:
                start = item["start"]
                end = (
                    self.FULL_VOLUME
                    if toward_full
                    else self.duck_to
                )
                vol = start + (end - start) * t

                for si in live:
                    if self._matches_target(si, item):
                        self._set_volume(pulse, si, vol)
                        break

            if interval:
                time.sleep(interval)

    def _lift_targets(self, pulse, items, label):
        if not items:
            return 0

        try:
            live = list(pulse.sink_input_list())
        except Exception:
            return 0

        lifted = 0

        for item in items:
            for si in live:
                if getattr(si, "mute", False):
                    continue

                if self._is_ours(si):
                    continue

                if self._matches_target(si, item):
                    if self._set_volume(
                        pulse,
                        si,
                        self.FULL_VOLUME,
                    ):
                        lifted += 1
                    break

        if lifted:
            log.debug(
                "restored %d audio stream(s) to 100%% (%s)",
                lifted,
                label,
            )

        return lifted

    # Best-effort: put every non-hai, non-muted sink-input back at 100%.
    # Safe to call from stop(), worker finally, or a CLI helper.
    # Does not touch this process's TTS stream while it is still live.
    @classmethod
    def restore_foreign_to_full(cls, exclude_pids=None):
        if not sys.platform.startswith("linux"):
            return

        with cls._restore_lock:
            ducker = cls(exclude_pids=exclude_pids)
            pulse = ducker._linux_pulse()

            if pulse is None:
                return

            try:
                lifted = 0

                for si in pulse.sink_input_list():
                    if getattr(si, "mute", False):
                        continue

                    if ducker._is_ours(si):
                        continue

                    try:
                        current = si.volume.value_flat
                    except Exception:
                        current = None

                    if (
                        current is not None
                        and current >= cls.FULL_VOLUME - 0.01
                    ):
                        continue

                    if ducker._set_volume(
                        pulse,
                        si,
                        cls.FULL_VOLUME,
                    ):
                        lifted += 1

                if lifted:
                    log.debug(
                        "recovered %d background stream(s) to 100%%",
                        lifted,
                    )

            except Exception as e:
                log.debug(
                    "background volume recovery failed: %s",
                    e,
                )

            finally:
                try:
                    pulse.close()
                except Exception:
                    pass

    def _linux_duck(self):
        pulse = self._linux_pulse()

        if pulse is None:
            return

        try:
            # Recover leftovers from a previous interrupted duck
            # before snapshotting.
            AudioDucker.restore_foreign_to_full(
                exclude_pids=self.exclude_pids
            )

            inputs = list(pulse.sink_input_list())
            known = {si.index for si in inputs}
            saved = {}
            targets = []

            for si in inputs:
                if getattr(si, "mute", False):
                    continue

                if self._is_ours(si):
                    continue

                try:
                    original = si.volume.value_flat
                except Exception:
                    continue

                props = self._proplist(si)
                target = {
                    "index": si.index,
                    "pid": props.get("application.process.id"),
                    "app": props.get("application.name"),
                    "media": props.get("media.name"),
                    "start": original,
                }

                targets.append(target)

                if original > self.duck_to:
                    saved[si.index] = original

            with self._lock:
                self._saved = saved
                self._targets = targets
                self._known = known

            self._ramp(
                pulse,
                [
                    target
                    for target in targets
                    if target["start"] > self.duck_to
                ],
                toward_full=False,
            )

            if saved:
                log.debug(
                    "ducked %d audio stream(s) to %.0f%%",
                    len(saved),
                    self.duck_to * 100,
                )

        except Exception as e:
            log.debug("linux duck failed: %s", e)

        finally:
            try:
                pulse.close()
            except Exception:
                pass

    def _linux_restore(self):
        with self._lock:
            targets = list(self._targets)
            self._saved = {}
            self._targets = []
            self._known = set()

        pulse = self._linux_pulse()

        if pulse is None:
            AudioDucker.restore_foreign_to_full(
                exclude_pids=self.exclude_pids
            )
            return

        try:
            for item in targets:
                item["start"] = self.duck_to

            self._ramp(
                pulse,
                targets,
                toward_full=True,
            )

            # Hard set to 100% so a missed fade step cannot leave
            # streams at 25%.
            self._lift_targets(
                pulse,
                targets,
                "ducked",
            )

        except Exception as e:
            log.debug("linux unduck failed: %s", e)

        finally:
            try:
                pulse.close()
            except Exception:
                pass

            AudioDucker.restore_foreign_to_full(
                exclude_pids=self.exclude_pids
            )
