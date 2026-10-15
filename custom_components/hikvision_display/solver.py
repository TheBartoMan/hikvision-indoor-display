"""Firmware-specific offline challenge verification; no online guesses."""
import array
import base64
import hashlib
from pathlib import Path
import re
import struct
import sys
import time
from .errors import StationError
ROOT = Path(__file__).resolve().parent

SEED_SHA256 = "200e39498a2629a77e10dccb029692118db4de233ce97ed354060108dd5d52b7"

MODULUS = int(
    "b2f82eb9cfc7d8ff4876735e4c6d91208afe41f3c50a9ba52eced3f0a11c58354"
    "d26c99aab11a8ad54885b7567912825ea43d87705a313e3f56231f9e6f02899e832"
    "31ff3ec3b1089edc239b43cde2918c4a41333de62c17bc5468747ac1de9be47615"
    "d1abcc08355d9ec4da5778c71f2d9bae0f339a729c2276d16c0549b65674128e06a"
    "928e50c5c18eb7ca16c347b6b0ad3a9bd175b8d228f01c6e4ca9d3cc8e4725c499"
    "f120948cb49bef5bebf705bb044c2046b56764be6c671106e0f5b4f635e3ba2fda3"
    "4796daa1f33fe5302aedcd058e8419c901317405d5d61309b6fe43ea69c95fab3507"
    "e8bb5261f5560626013b26c2f54c028c893612be51c743", 16)

class Rng:
    """The firmware's uClibc TYPE_3 generator, with explicit 32-bit arithmetic."""
    def __init__(self, seed):
        value = seed or 1
        self.state = [value]
        for _ in range(30):
            value = (16807 * value) % 2147483647
            self.state.append(value)
        self.front, self.rear = 3, 0
        for _ in range(310):
            self.next()

    def next(self):
        value = (self.state[self.front] + self.state[self.rear]) & 0xFFFFFFFF
        self.state[self.front] = value
        self.front = (self.front + 1) % 31
        self.rear = (self.rear + 1) % 31
        return value >> 1

def load_seeds(path=ROOT / "seeds.bin"):
    data = path.read_bytes()
    if len(data) != 4000000 or hashlib.sha256(data).hexdigest() != SEED_SHA256:
        raise StationError("Seed table missing or invalid")
    values = array.array("I")
    values.frombytes(data)
    if sys.byteorder != "little":
        values.byteswap()
    if values[0] != 1804289383 or values[1] != 1804289383:
        raise StationError("Seed table self-test failed")
    return values

def parse_challenge(text):
    long_values, short_values = [], []
    for line in text.replace(b"\r", b"").splitlines():
        line = line.strip()
        if not re.fullmatch(rb"[A-Za-z0-9+/]{18,}={0,2}", line):
            continue
        try:
            value = base64.b64decode(line, validate=True)
        except ValueError:
            continue
        if value[:4] != b"\x0c\0\0\0":
            continue
        if len(value) == 260:
            long_values.append(value)
        elif len(value) == 14:
            short_values.append(value)
    if len(long_values) != 1 or len(short_values) != 1:
        raise StationError("Unrecognized Debug challenge; no response sent")
    return long_values[0], short_values[0]

def solve_challenge(long_value, short_value, seeds, seconds=12, window=128):
    if (len(long_value), len(short_value)) != (260, 14):
        raise StationError("Invalid challenge length")
    expected = struct.unpack_from("<I", short_value, 10)[0]
    deadline = time.monotonic() + seconds
    seed_matches = [seed for seed, value in enumerate(seeds) if value == expected]
    ciphertext = int.from_bytes(long_value[4:], "big")
    for seed1 in seed_matches:
        candidates = [(seed1 + delta) % 1000000 for delta in range(window + 1)]
        first = {seed: struct.pack("<I", Rng(seed).next()) for seed in candidates}
        for index, seed3 in enumerate(candidates):
            rng = Rng(seed3)
            rng.next()
            padding = bytearray()
            while len(padding) < 245:
                value = rng.next() & 255
                if value:
                    padding.append(value)
            for seed2 in candidates[:index + 1]:
                if time.monotonic() > deadline:
                    raise StationError("Offline solver timed out; no response sent")
                response = base64.b64encode(first[seed2] + first[seed3][:2])
                block = b"\0\2" + padding + b"\0" + response
                if pow(int.from_bytes(block, "big"), 65537, MODULUS) == ciphertext:
                    return response.decode("ascii")
    raise StationError("No verified response found; no unlock guess sent")
