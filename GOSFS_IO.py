class Disk:
    def __init__(self, disk: str = "disk.img"):
        self.disk = open(disk, "r+b")

    def read_sector(self, sector: int):
        self.disk.seek(sector * 512)
        data = self.disk.read(512)

        if len(data) != 512:
            raise IOError(f"could not read sector {sector}")

        return data

    def write_sector(self, sector, data):
        if len(data) > 512:
            raise ValueError("sector write cannot exceed 512 bytes")
        data = data + bytes(512 - len(data))
        self.disk.seek(sector * 512)
        self.disk.write(data)

    def close(self):
        self.disk.close()