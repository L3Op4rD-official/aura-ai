import struct
import zlib

def create_favicon():
    png_data = create_png_icon()

    with open('static/favicon.ico', 'wb') as f:
        f.write(b'\x00\x00')
        f.write(struct.pack('<H', 1))
        f.write(struct.pack('<H', 1))
        f.write(struct.pack('<B', 32))
        f.write(struct.pack('<B', 32))
        f.write(b'\x00')
        f.write(b'\x00')
        f.write(struct.pack('<H', 1))
        f.write(struct.pack('<I', 32))
        f.write(struct.pack('<I', 22))
        f.write(png_data)

    print("favicon.ico created in static/ folder!")

def create_png_icon():
    width, height = 32, 32

    def png_chunk(chunk_type, data):
        chunk_len = struct.pack('>I', len(data))
        chunk_crc = struct.pack('>I', zlib.crc32(chunk_type + data) & 0xffffffff)
        return chunk_len + chunk_type + data + chunk_crc

    signature = b'\x89PNG\r\n\x1a\n'

    ihdr_data = struct.pack('>IIBBBBB', width, height, 8, 6, 0, 0, 0)
    ihdr = png_chunk(b'IHDR', ihdr_data)

    raw_pixels = []
    for y in range(height):
        raw_pixels.append(0)
        for x in range(width):
            r, g, b, a = get_pixel_color(x, y, width, height)
            raw_pixels.extend([r, g, b, a])

    raw_data = bytes(raw_pixels)
    compressed = zlib.compress(raw_data, 9)
    idat = png_chunk(b'IDAT', compressed)

    iend = png_chunk(b'IEND', b'')

    return signature + ihdr + idat + iend

def get_pixel_color(x, y, width, height):
    cx, cy = width // 2, height // 2
    hex_radius = 14
    inner_hex_radius = 10

    def point_in_hex(px, py, radius):
        qx = px - cx
        qy = py - cy
        if abs(qx) + abs(qy) > radius * 1.5:
            return False
        if abs(qx) > radius or abs(qy) > radius:
            return False
        return True

    def point_in_letter_a(px, py):
        letter_x = cx - 8
        letter_y = cy - 10
        lx = px - letter_x
        ly = py - letter_y

        if ly < 0 or ly > 20:
            return False

        if ly < 10:
            left_bound = 2 + (ly / 10) * 6
            right_bound = 14 - (ly / 10) * 6
            cross_bar = 8 <= ly <= 10 and 4 <= lx <= 12
        else:
            left_bound = 8
            right_bound = 8
            cross_bar = ly >= 10 and 4 <= lx <= 12

        in_triangle = left_bound <= lx <= right_bound or cross_bar
        return in_triangle

    if not point_in_hex(x, y, hex_radius):
        return 0, 0, 0, 0

    inner_hex = point_in_hex(x, y, inner_hex_radius)

    if point_in_letter_a(x, y):
        return 0, 255, 65, 255

    if inner_hex:
        return 10, 10, 10, 255

    return 0, 0, 0, 0

if __name__ == '__main__':
    create_favicon()
    print("Done! favicon.ico is ready in static folder.")