#!/usr/bin/env python3
"""
Serial shell helper: interactive terminal, single-command, or batch-script
execution over a serial port.  Optimised for talking to embedded Linux / RTOS
shells and bootloader CLIs.

Requires: pip install pyserial
"""

from __future__ import annotations

import argparse
import os
import re
import signal
import sys
import threading
import time
from pathlib import Path

try:
    import serial
    from serial import Serial, SerialException
except ImportError as e:
    print("Missing dependency: install with  pip install pyserial", file=sys.stderr)
    raise SystemExit(1) from e


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _open_port(
    port: str,
    baud: int,
    bytesize: int,
    parity: str,
    stopbits: float,
    timeout: float,
) -> Serial:
    parity_map = {
        "N": serial.PARITY_NONE,
        "E": serial.PARITY_EVEN,
        "O": serial.PARITY_ODD,
        "M": serial.PARITY_MARK,
        "S": serial.PARITY_SPACE,
    }
    stop_map = {
        1: serial.STOPBITS_ONE,
        1.5: serial.STOPBITS_ONE_POINT_FIVE,
        2: serial.STOPBITS_TWO,
    }
    size_map = {
        5: serial.FIVEBITS,
        6: serial.SIXBITS,
        7: serial.SEVENBITS,
        8: serial.EIGHTBITS,
    }

    if bytesize not in size_map:
        raise ValueError(f"unsupported bytesize {bytesize}")
    if parity.upper() not in parity_map:
        raise ValueError(f"unsupported parity {parity}")
    if stopbits not in stop_map:
        raise ValueError(f"unsupported stopbits {stopbits}")

    return Serial(
        port=port,
        baudrate=baud,
        bytesize=size_map[bytesize],
        parity=parity_map[parity.upper()],
        stopbits=stop_map[stopbits],
        timeout=timeout,
    )


def _line_ending(crlf: bool) -> bytes:
    return b"\r\n" if crlf else b"\n"


def _rs485_send(
    ser: Serial,
    data: bytes,
    rs485: bool,
    rs485_delay: float,
    rs485_bytewise: bool = False,
) -> None:
    """Send bytes over the serial port, with optional RS-485 half-duplex RTS control.

    Two RS-485 modes:
      - Burst (rs485_bytewise=False): toggle RTS once for the entire write.
        Fast, but the device's per-character echo is lost during TX.
      - Bytewise (rs485_bytewise=True): toggle RTS per *byte* so the adapter
        switches back to RX between characters, capturing the shell echo.
        Slower but correct for half-duplex shells that echo character-by-character.
    """
    if not rs485:
        ser.write(data)
        return

    if rs485_bytewise:
        # Per-byte RTS toggle — catches the shell's per-character echo.
        for b in data:
            ser.rts = True
            ser.write(bytes([b]))
            ser.flush()
            if rs485_delay > 0:
                time.sleep(rs485_delay)
            ser.rts = False
            # tiny gap for transceiver to settle into RX
            time.sleep(0.002)
    else:
        ser.rts = True
        ser.write(data)
        ser.flush()
        if rs485_delay > 0:
            time.sleep(rs485_delay)
        ser.rts = False


def _drain(ser: Serial, duration: float = 0.3) -> bytes:
    """Read and discard any data already in the device's output buffer."""
    ser.timeout = 0.1
    drained = bytearray()
    deadline = time.monotonic() + duration
    while time.monotonic() < deadline:
        chunk = ser.read(4096)
        if chunk:
            drained.extend(chunk)
        else:
            time.sleep(0.05)
    return bytes(drained)


def _wakeup(
    ser: Serial,
    eol: bytes,
    rs485: bool,
    rs485_delay: float,
    rs485_bytewise: bool = False,
    drain_duration: float = 0.3,
    extra_lines: int = 1,
) -> None:
    """Send one or more blank lines to flush stale data from the device's
    input buffer, then drain the echoed response.  Essential after opening
    a half-duplex RS-485 port because the device may have unprocessed bytes
    left over from a previous session."""
    for _ in range(extra_lines):
        _rs485_send(ser, eol, rs485, rs485_delay, rs485_bytewise)
        time.sleep(0.05)
    _drain(ser, drain_duration)


# ---------------------------------------------------------------------------
# interactive mode
# ---------------------------------------------------------------------------

def run_interactive(
    port: str,
    baud: int,
    bytesize: int,
    parity: str,
    stopbits: float,
    echo_hex: bool,
    crlf: bool,
    encoding: str,
    log_file: str | None,
    init_commands: list[str],
    init_delay: float,
    rs485: bool,
    rs485_delay: float,
    rs485_bytewise: bool,
) -> None:
    """Open the port, run any init commands, then drop into an interactive
    terminal: typed lines are sent to the device, received bytes are printed
    to stdout.  Ctrl+] (0x1d) exits cleanly."""

    ser = _open_port(port, baud, bytesize, parity, stopbits, timeout=0.1)
    stop = threading.Event()
    eol = _line_ending(crlf)
    log_fh = open(log_file, "a", encoding=encoding, errors="replace") if log_file else None

    def reader() -> None:
        """Read thread – pushes every byte from the serial port to stdout
        (and optionally to the log file)."""
        try:
            while not stop.is_set():
                chunk = ser.read(4096)
                if not chunk:
                    continue
                if echo_hex:
                    line = chunk.hex(" ") + "\n"
                    sys.stdout.buffer.write(line.encode("ascii"))
                else:
                    sys.stdout.buffer.write(chunk)
                    if log_fh:
                        log_fh.write(chunk.decode(encoding, errors="replace"))
                        log_fh.flush()
                sys.stdout.buffer.flush()
        except SerialException as ex:
            if not stop.is_set():
                print(f"\n[reader] {ex}", file=sys.stderr)

    # flush stale data from the device's input buffer (before reader thread to
    # avoid concurrent reads on the serial port)
    _wakeup(ser, eol, rs485, rs485_delay, rs485_bytewise)

    t = threading.Thread(target=reader, daemon=True)
    t.start()

    # send init commands
    for cmd in init_commands:
        _rs485_send(ser, cmd.encode(encoding, errors="replace") + eol, rs485, rs485_delay, rs485_bytewise)
        time.sleep(init_delay)

    tag = "[RS-485]" if rs485 else ""
    print(
        f"Opened {port} @ {baud} {bytesize}{parity}{int(stopbits) if stopbits == int(stopbits) else stopbits} {tag}. "
        "Type commands; Ctrl+] to exit.",
        file=sys.stderr,
    )

    try:
        while not stop.is_set():
            # read a single character from stdin so we can trap Ctrl+]
            ch = sys.stdin.buffer.read(1)
            if not ch:
                break
            if ch == b"\x1d":  # Ctrl+]
                print("\n[shell] exiting…", file=sys.stderr)
                _rs485_send(ser, b"exit" + eol, rs485, rs485_delay, rs485_bytewise)
                time.sleep(0.3)
                break
            _rs485_send(ser, ch, rs485, rs485_delay, rs485_bytewise)
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        ser.close()
        if log_fh:
            log_fh.close()
        t.join(timeout=2.0)


# ---------------------------------------------------------------------------
# single-command mode
# ---------------------------------------------------------------------------

def run_single_command(
    port: str,
    baud: int,
    bytesize: int,
    parity: str,
    stopbits: float,
    command: str,
    timeout_sec: float,
    echo_hex: bool,
    crlf: bool,
    encoding: str,
    log_file: str | None,
    init_commands: list[str],
    init_delay: float,
    prompt_pattern: str | None,
    rs485: bool,
    rs485_delay: float,
    rs485_bytewise: bool,
) -> None:
    """Send one command, collect output until *timeout_sec* of silence or a
    prompt match, then print and exit."""

    ser = _open_port(port, baud, bytesize, parity, stopbits, timeout=0.1)
    eol = _line_ending(crlf)
    stop = threading.Event()
    log_fh = open(log_file, "a", encoding=encoding, errors="replace") if log_file else None

    output_parts: list[bytes] = []
    prompt_re = re.compile(prompt_pattern.encode(encoding, errors="replace")) if prompt_pattern else None

    last_rx = time.monotonic()

    def reader() -> None:
        nonlocal last_rx
        try:
            while not stop.is_set():
                chunk = ser.read(4096)
                if not chunk:
                    continue
                last_rx = time.monotonic()
                output_parts.append(chunk)
        except SerialException:
            pass

    # flush stale data from the device's input buffer (before reader thread to
    # avoid concurrent reads on the serial port)
    _wakeup(ser, eol, rs485, rs485_delay, rs485_bytewise)

    # reset last_rx *after* the wakeup drain so the timeout counts from now
    last_rx = time.monotonic()

    t = threading.Thread(target=reader, daemon=True)
    t.start()

    # send init commands
    for cmd in init_commands:
        _rs485_send(ser, cmd.encode(encoding, errors="replace") + eol, rs485, rs485_delay, rs485_bytewise)
        time.sleep(init_delay)

    # send the actual command
    _rs485_send(ser, command.encode(encoding, errors="replace") + eol, rs485, rs485_delay, rs485_bytewise)

    # wait for silence or prompt
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        time.sleep(0.05)
        # check prompt pattern first
        if prompt_re and output_parts:
            tail = b"".join(output_parts[-8:])  # look at last few chunks
            if prompt_re.search(tail):
                break
        if time.monotonic() - last_rx > timeout_sec:
            break

    stop.set()
    ser.close()
    t.join(timeout=1.0)

    output = b"".join(output_parts)
    if echo_hex:
        sys.stdout.buffer.write(output.hex(" ").encode("ascii") + b"\n")
    else:
        sys.stdout.buffer.write(output)

    if log_fh:
        log_fh.write(output.decode(encoding, errors="replace"))
        log_fh.close()


# ---------------------------------------------------------------------------
# batch-script mode
# ---------------------------------------------------------------------------

def run_script(
    port: str,
    baud: int,
    bytesize: int,
    parity: str,
    stopbits: float,
    script_path: str,
    timeout_sec: float,
    echo_hex: bool,
    crlf: bool,
    encoding: str,
    log_file: str | None,
    init_commands: list[str],
    init_delay: float,
    prompt_pattern: str | None,
    rs485: bool,
    rs485_delay: float,
    rs485_bytewise: bool,
) -> None:
    """Read commands from a text file, send them one at a time, printing the
    response after each."""

    script = Path(script_path)
    if not script.is_file():
        print(f"Script file not found: {script_path}", file=sys.stderr)
        raise SystemExit(1)

    commands: list[str] = []
    for raw in script.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        commands.append(line)

    if not commands:
        print("No commands found in script.", file=sys.stderr)
        return

    ser = _open_port(port, baud, bytesize, parity, stopbits, timeout=0.1)
    eol = _line_ending(crlf)
    stop = threading.Event()
    log_fh = open(log_file, "a", encoding=encoding, errors="replace") if log_file else None

    output_parts: list[bytes] = []
    prompt_re = re.compile(prompt_pattern.encode(encoding, errors="replace")) if prompt_pattern else None
    last_rx = time.monotonic()

    def reader() -> None:
        nonlocal last_rx
        try:
            while not stop.is_set():
                chunk = ser.read(4096)
                if not chunk:
                    continue
                last_rx = time.monotonic()
                output_parts.append(chunk)
        except SerialException:
            pass

    # flush stale data from the device's input buffer (before reader thread to
    # avoid concurrent reads on the serial port)
    _wakeup(ser, eol, rs485, rs485_delay, rs485_bytewise)

    # reset last_rx *after* the wakeup drain so the timeout counts from now
    last_rx = time.monotonic()

    t = threading.Thread(target=reader, daemon=True)
    t.start()

    # send init commands
    for cmd in init_commands:
        _rs485_send(ser, cmd.encode(encoding, errors="replace") + eol, rs485, rs485_delay, rs485_bytewise)
        time.sleep(init_delay)

    for cmd in commands:
        print(f"\n--- $ {cmd} ---", file=sys.stderr)
        output_parts.clear()
        _rs485_send(ser, cmd.encode(encoding, errors="replace") + eol, rs485, rs485_delay, rs485_bytewise)

        deadline = time.monotonic() + timeout_sec
        while time.monotonic() < deadline:
            time.sleep(0.05)
            if prompt_re and output_parts:
                tail = b"".join(output_parts[-8:])
                if prompt_re.search(tail):
                    break
            if time.monotonic() - last_rx > timeout_sec:
                break

        output = b"".join(output_parts)
        if echo_hex:
            sys.stdout.buffer.write(output.hex(" ").encode("ascii") + b"\n")
        else:
            sys.stdout.buffer.write(output)

        if log_fh:
            log_fh.write(output.decode(encoding, errors="replace"))
            log_fh.flush()

    stop.set()
    ser.close()
    t.join(timeout=1.0)

    if log_fh:
        log_fh.close()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    p = argparse.ArgumentParser(
        description="Serial shell helper – interactive, single-command, or batch mode.",
    )
    p.add_argument("-p", "--port", help="Serial device (e.g. COM3 or /dev/ttyUSB0)")
    p.add_argument("-b", "--baud", type=int, default=115200, help="Baud rate (default 115200)")
    p.add_argument("--bytesize", type=int, default=8, choices=[5, 6, 7, 8])
    p.add_argument("--parity", default="N", help="N E O M S (default N)")
    p.add_argument("--stopbits", type=float, default=1, choices=[1, 1.5, 2])

    # operation mode (mutually exclusive)
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--cmd", metavar="CMD", help="Send a single command and capture output")
    mode.add_argument("--script", metavar="FILE", help="Execute commands from a file line by line")

    # shell behaviour
    p.add_argument("--hex", action="store_true", help="Print received bytes as hex")
    p.add_argument("--crlf", action="store_true", help="Send CR+LF as line ending (default: LF only)")
    p.add_argument("--encoding", default="utf-8", help="Serial text encoding (default utf-8)")
    p.add_argument("--timeout", type=float, default=3.0, help="Response silence timeout in seconds (default 3)")
    p.add_argument("--prompt", metavar="PATTERN", help="Regex pattern matching the shell prompt (e.g. '# ' or '\\$ ')")
    p.add_argument("--log", metavar="FILE", help="Log all received data to a file")
    p.add_argument(
        "--init",
        metavar="CMD",
        action="append",
        default=[],
        help="Command(s) to send on connect (repeatable). Use for login, cd, etc.",
    )
    p.add_argument(
        "--init-delay",
        type=float,
        default=0.5,
        help="Delay in seconds between init commands (default 0.5)",
    )
    p.add_argument(
        "--rs485",
        action="store_true",
        help="RS-485 half-duplex mode: toggle RTS before/after each write to control the transceiver",
    )
    p.add_argument(
        "--rs485-delay",
        type=float,
        default=0.005,
        help="Extra delay (seconds) after TX flush before switching RTS back to RX (default 0.005)",
    )
    p.add_argument(
        "--rs485-byte",
        action="store_true",
        dest="rs485_bytewise",
        help="RS-485 bytewise mode: toggle RTS after *each byte* to capture the shell per-character echo. Slower but essential for half-duplex shells",
    )

    args = p.parse_args()

    if not args.port:
        p.error("--port is required unless using -h")

    if args.cmd:
        run_single_command(
            port=args.port,
            baud=args.baud,
            bytesize=args.bytesize,
            parity=args.parity,
            stopbits=args.stopbits,
            command=args.cmd,
            timeout_sec=args.timeout,
            echo_hex=args.hex,
            crlf=args.crlf,
            encoding=args.encoding,
            log_file=args.log,
            init_commands=args.init,
            init_delay=args.init_delay,
            prompt_pattern=args.prompt,
            rs485=args.rs485,
            rs485_delay=args.rs485_delay,
            rs485_bytewise=args.rs485_bytewise,
        )
    elif args.script:
        run_script(
            port=args.port,
            baud=args.baud,
            bytesize=args.bytesize,
            parity=args.parity,
            stopbits=args.stopbits,
            script_path=args.script,
            timeout_sec=args.timeout,
            echo_hex=args.hex,
            crlf=args.crlf,
            encoding=args.encoding,
            log_file=args.log,
            init_commands=args.init,
            init_delay=args.init_delay,
            prompt_pattern=args.prompt,
            rs485=args.rs485,
            rs485_delay=args.rs485_delay,
            rs485_bytewise=args.rs485_bytewise,
        )
    else:
        run_interactive(
            port=args.port,
            baud=args.baud,
            bytesize=args.bytesize,
            parity=args.parity,
            stopbits=args.stopbits,
            echo_hex=args.hex,
            crlf=args.crlf,
            encoding=args.encoding,
            log_file=args.log,
            init_commands=args.init,
            init_delay=args.init_delay,
            rs485=args.rs485,
            rs485_delay=args.rs485_delay,
            rs485_bytewise=args.rs485_bytewise,
        )


if __name__ == "__main__":
    main()
