import os


class Spinner:
    """One character at the cursor. Cleared before real output."""

    SPIN = "|/-\\"

    def __init__(self, fd: int) -> None:
        self.fd = fd
        self.frame = 0
        self.on = False

    def tick(self) -> None:
        ch = Spinner.SPIN[self.frame % len(Spinner.SPIN)].encode()
        self.frame += 1
        try:
            if self.on:
                os.write(self.fd, b"\x08" + ch)
            else:
                os.write(self.fd, b"\x1b[?25l" + ch)
                self.on = True
        except OSError:
            pass

    def clear(self) -> None:
        if not self.on:
            return
        try:
            os.write(self.fd, b"\x08 \x08\x1b[?25h")
        except OSError:
            pass
        self.on = False

