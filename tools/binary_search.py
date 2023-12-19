import argparse
from io import BytesIO
import struct

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('file',
                        help='file to search')
    parser.add_argument('--float', required=False,
                        help='search for a float')
    
    args = parser.parse_args()
    file = args.file

    with open(file, "rb") as f:
        target_size = 4

        parts = args.float.split('.')
        if len(parts) == 2:
            num_decimals = len(parts[1])

            # Get nearby float values
            target = float(args.float)
            target_floor = target - 10**(-num_decimals)
            target_ceil = target + 10**(-num_decimals)
        else:
            target_floor = target_ceil = float(args.float)

        chunk_size = 1024
        while f.readable():
            fpos = f.tell()
            data = f.read(chunk_size)
            if not data or len(data) < target_size:
                break

            # Search for target
            for i in range(0, len(data) - target_size + 1):
                chunk = data[i:i+target_size]
                if len(chunk) < target_size:
                    continue

                # Convert to float
                num = struct.unpack('<f', chunk)[0]
                if num >= target_floor and num <= target_ceil:
                    pos = fpos + i
                    print(f'Found {num} at {pos} (0x{pos:x})')

            f.seek(f.tell() - target_size + 1)