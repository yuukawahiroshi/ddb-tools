from __future__ import annotations
from typing import Optional
import struct
import io

class RawData:
    name: Optional[str]
    data_type: str
    data_len: int
    offset: Optional[int]
    value: bytes

    def __init__(self, data_type: str, bytes: int):
        self.name = None
        self.data_type = data_type
        self.offset = 0
        self.data_len = bytes
        self.value = None

    def parse(self, data: bytes) -> None:
        self.value = data

    def parse_from_file(self, file: io.BytesIO) -> None:
        self.offset = file.tell()
        bin_value = file.read(self.data_len)
        self.parse(bin_value)

    def serialize(self) -> bytes:
        raise NotImplementedError
    
    def write_to_file(self, file: io.BytesIO) -> None:
        file.write(self.serialize())

    def overwrite(self, file: io.BytesIO) -> None:
        file.seek(self.offset)
        self.write_to_file(file)


class Int(RawData):
    value: int

    def __init__(self, length: int = 4):
        super().__init__('int', length)

    def parse(self, data: bytes) -> None:
        self.value = int.from_bytes(data, 'little')

    def serialize(self) -> bytes:
        return self.value.to_bytes(self.data_len, 'little')


class Int16(Int):
    def __init__(self):
        super().__init__(2)


class Int32(Int):
    def __init__(self):
        super().__init__(4)


class Int64(Int):
    def __init__(self):
        super().__init__(8)
    

class Float32(RawData):
    value: float

    def __init__(self):
        super().__init__('float32', 4)

    def parse(self, data: bytes) -> None:
        self.value = struct.unpack('<f', data)[0]

    def serialize(self) -> bytes:
        return struct.pack('<f', self.value)


class Float64(RawData):
    value: float

    def __init__(self):
        super().__init__('float64', 8)

    def parse(self, data: bytes) -> None:
        self.value = struct.unpack('<d', data)[0]

    def serialize(self) -> bytes:
        return struct.pack('<d', self.value)


class VString(RawData):
    value: str

    def __init__(self):
        super().__init__('dstring', 0)

    def parse(self, data: bytes) -> None:
        str_size = int.from_bytes(data[0:4], byteorder='little')
        self.value = data[4:4 + str_size].decode('ascii')
        self.data_len = 4 + str_size

    def parse_from_file(self, file: io.BytesIO) -> None:
        str_size = int.from_bytes(file.read(4), byteorder='little')
        self.value = file.read(str_size).decode('ascii')
        self.data_len = 4 + str_size

    def serialize(self) -> bytes:
        str_bytes = self.value.encode('ascii')
        return len(str_bytes).to_bytes(4, byteorder='little') + str_bytes