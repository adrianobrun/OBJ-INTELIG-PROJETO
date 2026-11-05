"""Decode the actual Wokwi logic analyzer recording (UART 9600 8N1)."""
import argparse
import bisect
import collections
import json
from pathlib import Path


def read_vcd(path):
    symbols, channels = {}, {}
    time = 0
    for line in Path(path).read_text().splitlines():
        fields = line.split()
        if line.startswith("$timescale") and fields[1] != "1ns":
            raise ValueError("Expected the Wokwi 1 ns timescale")
        if line.startswith("$var"):
            symbols[fields[3]] = fields[4]
            channels[fields[4]] = []
        elif line.startswith("#"):
            time = int(line[1:])
        elif line and line[0] in "01" and line[1:] in symbols:
            changes = channels[symbols[line[1:]]]
            value = int(line[0])
            if changes and changes[-1][0] == time:
                changes[-1] = (time, value)
            elif not changes or changes[-1][1] != value:
                changes.append((time, value))
    return channels


def decode_uart(changes, baud=9600):
    times = [t for t, value in changes]
    values = [value for t, value in changes]
    bit = 1e9 / baud
    ready = 0
    data, framing_errors = [], []
    for index, (time, value) in enumerate(changes):
        if value or index == 0 or not values[index - 1] or time < ready:
            continue
        def sample(offset):
            return values[bisect.bisect_right(times, time + offset * bit) - 1]
        if sample(0.5) != 0:
            continue
        byte = sum(sample(1.5 + i) << i for i in range(8))
        if sample(9.5) != 1:
            framing_errors.append(time)
        data.append((time, byte))
        ready = time + 9.75 * bit
    return data, framing_errors


def pms_frames(data):
    frames, index = [], 0
    while index + 32 <= len(data):
        raw = bytes(byte for time, byte in data[index:index + 32])
        if raw[:2] != b"\x42\x4d":
            index += 1
            continue
        word = lambda offset: int.from_bytes(raw[offset:offset + 2], "big")
        frames.append({
            "time_s": round(data[index][0] / 1e9, 6),
            "hex": raw.hex(" "), "length": word(2),
            "pm1": word(10), "pm25": word(12), "pm10": word(14),
            "checksum": word(30), "sum": sum(raw[:30]),
            "valid": word(2) == 28 and word(30) == sum(raw[:30]),
        })
        index += 32
    return frames


def summarize(path, uart_channel):
    channels = read_vcd(path)
    data, errors = decode_uart(channels[uart_channel])
    frames = pms_frames(data)
    triples = collections.Counter((f["pm1"], f["pm25"], f["pm10"], f["valid"]) for f in frames)
    return {
        "source": Path(path).name, "baud": 9600, "format": "8N1",
        "bytes": len(data), "framing_errors": len(errors),
        "frame_count": len(frames), "valid_frames": sum(f["valid"] for f in frames),
        "samples": [{"pm1": a, "pm25": b, "pm10": c, "valid": d, "frames": count}
                    for (a, b, c, d), count in triples.items()],
        "frames": frames,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("capture")
    parser.add_argument("--channel", default="D0")
    parser.add_argument("--out")
    args = parser.parse_args()
    result = summarize(args.capture, args.channel)
    if args.out:
        Path(args.out).write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({key: value for key, value in result.items() if key != "frames"}, indent=2))
