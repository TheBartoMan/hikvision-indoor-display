"""Sanitized, immutable catalog from a complete diagnostic response."""
from dataclasses import dataclass
import re

from .errors import StationError

ROW = re.compile(r"^\[(\d+)\]devName:(.*), ip:([^,\r\n]+), devType:(\d+), "
                 r"devId:(\d+), videoEncType:(\d+)-(\d+)\s*$")


@dataclass(frozen=True)
class Camera:
    slot: int
    name: str
    kind: str
    device_id: int
    sequence: int
    label: str

    @property
    def key(self):
        return f"{self.kind}:{self.device_id}"


def parse_catalog(text):
    counts = re.findall(r"(?m)^devNum:(\d+)\s*$", text)
    if len(counts) != 1 or not 0 <= int(counts[0]) <= 50:
        raise StationError("Invalid camera catalog count")
    rows = []
    for line in text.splitlines():
        if re.match(r"^\[\d+\]devName:", line):
            match = ROW.fullmatch(line.strip())
            if not match:
                raise StationError("Invalid camera catalog row")
            rows.append(match.groups())
    if len(rows) != int(counts[0]):
        raise StationError("Incomplete camera catalog")
    names = [row[1] for row in rows]
    sequences = {"ipc": 0, "outdoor": 0}
    cameras = []
    for index, (slot, name, _ip, device_type, device_id, _enc, _audio) in enumerate(rows):
        kind = {2: "ipc", 3: "outdoor"}.get(int(device_type))
        if (int(slot) != index or kind is None or not 1 <= len(name) <= 80
                or name != name.strip() or any(ord(char) < 32 for char in name)):
            raise StationError("Unsupported or inconsistent camera catalog")
        sequences[kind] += 1
        if sequences[kind] > (16 if kind == "ipc" else 9):
            raise StationError("Camera count exceeds supported display limits")
        label = name if names.count(name) == 1 else f"{name} [{kind}:{int(device_id)}]"
        cameras.append(Camera(index, name, kind, int(device_id), sequences[kind], label))
    if (len({camera.key for camera in cameras}) != len(cameras)
            or len({camera.label for camera in cameras}) != len(cameras)):
        raise StationError("Ambiguous camera catalog")
    return tuple(cameras)


def resolve_camera(label, cameras):
    matches = [camera for camera in cameras if label == camera.label]
    if len(matches) != 1:
        raise StationError("Camera was removed or renamed; choose a current option")
    return matches[0]
