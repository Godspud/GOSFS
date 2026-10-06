"""Yep. Given the code you have right now, I'd turn that 10-sprint plan into a much more concrete checklist, while keeping the order. The important thing is don't start FUSE yet—your storage layer still has a few structural bugs.

Sprint 1 — Fix what's broken
Superblock / allocation
 Implement GOSFSSuperblockNode.is_free(relative_sector)
 Validate 0 <= relative_sector < 512
 Extract the 2-bit value
 Return True only for 0b00
 Make find_free_sector() use is_free()
 Make sure is_sector_free(absolute_sector) correctly converts:
absolute sector → superblock sector
absolute sector → relative sector
 Make sure the superblock's own sector can never be returned as free
File loading
 Fix GOSFSFileNode.load()
 Validate the sector's allocation type is 0b01
 Parse filename/extension safely
 Validate lengths don't run outside the 512-byte sector
 Set node.sector = sector
 Make sure load() produces the same object that save() originally wrote
File reading
 Fix inline data reading
 Fix directly allocated range reading
 Fix extent traversal:
 Start with self.extent, not self.sector
 Load extent
 Read its inline data
 Read its direct range
 Follow extent.extent
 Stop at 0
 Empty file returns b""
 read(offset, size) respects:
 offset
 size
 self.size
 Don't return padding bytes past logical size
Saving / writing
 Separate serializing the node from writing file data
 Remove the save() → write_data() → save() recursion
 Decide exactly what save() does:
 write metadata
 write currently allocated inline data
 nothing else
 Decide exactly what write_data() does:
 modify logical file contents
 ensure capacity
 distribute bytes
 update size
 call save()
Range growth

You currently have both:

def grow_range(node, additional_bytes):

and:

def _grow_range(self, wanted):
 Pick one implementation
 Delete the duplicate
 Make sure it works for both:
 GOSFSFileNode
 GOSFSExtentNode
 Make sure it never allocates a sector that isn't free
 Make sure allocation bitmap changes to 0b11
Naming / obvious bugs
 Pick inline_space() or inline_capacity()
 Use the same name everywhere
 Fix GOSFSExtentNode.save():
 HEADER → FORMAT
 Fix load_from_file() if it isn't actually needed
 Remove temporary debugging code from GOSFS.__init__
Sprint 1 test

Fresh image:

format
↓
create file
↓
save
↓
load
↓
read
↓
compare
 No crashes
 Metadata matches
 Filename matches
 Extension matches
 Size matches
 Data matches
 Bitmap matches
Sprint 2 — write_data() inline-only

Don't touch extents yet.

Implement _distribute()

It should conceptually do:

file contents
    │
    ├── first inline_space() bytes → node sector
    │
    └── remaining bytes → direct range

For Sprint 2, though, the remaining bytes should not exist because we're testing inline-only.

TODO
 Implement _distribute(contents)
 Calculate inline capacity from the node's current filename/extension
 Put the first bytes into self.data
 Don't accidentally include sector padding in self.data
 Make self.data represent actual inline data, not all 512 bytes
 Implement write_data(offset, data)
 Handle writing at offset 0
 Handle overwriting existing bytes
 Handle writing past EOF
 Update self.size
 Call _ensure_capacity()
 Call _distribute()
 Call save()
Test

Something like:

create empty file
write b"hello world"
save
load fresh object
read()
→ b"hello world"

Then:

 overwrite beginning
 overwrite middle
 append
 write beyond EOF
 reload after every test
Sprint 3 — write_data() growth

Now make storage actually grow.

Direct range
 Determine how much data fits inline
 Determine how many extra bytes are needed
 _ensure_capacity() grows the direct range
 _grow_range() allocates consecutive sectors
 Bitmap changes:
00 → 11
 length increments correctly
 _distribute() writes remaining data into those sectors
Extent creation

When the direct range can't grow:

 Create an ExtentNode
 Allocate its node sector as 0b10
 Set self.extent
 Save the file
 Put remaining data into the extent
 Grow the extent's direct range when necessary
Extent chaining
 Create extent A
 Fill extent A
 Create extent B
 Set:
A.extent = B.sector
B.parent = A.sector
 Continue until all data fits
Test sizes

Do actual escalating tests:

10 B
100 B
400 B
500 B
512 B
1 KB
2 KB
4 KB
8 KB

For each:

 write
 save
 create a completely new object with load()
 read
 compare exact bytes
Sprint 4 — Flags + DirNode skeleton
Flags

Stop doing:

if flags == 0b00000001:

Create constants.

For example:

FLAG_DIR
FLAG_LINK
FLAG_HIDDEN
FLAG_COMPRESSED
FLAG_INVALID
 Define them
 Replace magic numbers
 Decide whether flags are mutually exclusive or bit flags
 Make file validation use them
 Make directory validation use them
Dirent

Implement:

child_sector
name_len
name
ext_len
ext
 pack()
 unpack()
 Calculate variable size
 Validate name ≤ 255
 Validate extension ≤ 15
DirNode
 Create DirNode
 Load DirNode
 Save DirNode
 Calculate inline space
 Implement read_dirents()
 Scan:
 inline
 direct range
 extent chain
 Stop at child_sector == 0
 Implement add_dirent()
 Check duplicate names
 Append new entry
Test

Manually construct:

directory
 ├── hello.txt
 └── test.bin

Then:

 save
 load
 read dirents
 verify both entries
Sprint 5 — Finish directories + root
Directory storage
 Grow direct range when inline space is exhausted
 Grow extents when direct range is exhausted
 Allow a dirent to cross a sector boundary
 Treat directory contents as one continuous byte stream

Conceptually:

inline
   ↓
direct sectors
   ↓
extent A
   ↓
extent B
Deletion / compaction

Implement:

remove_dirent(...)
 Find target
 Remove its bytes
 Shift everything after it left
 Update directory length
 Keep allocated capacity
 Don't leave holes
 Keep child_sector == 0 after the last entry
Root

This is important.

Fresh filesystem:

sector 0
    ↓
root directory
 Create root directory during format
 Root's parent = 0
 Set header.root_sector
 Save header
 Mark root sector 0b01
 Make resolve_path("/") return header.root_sector
Path resolution

Implement:

/
 /home
 /home/test.txt
 /home/foo/bar.txt
 Split path
 Start at root
 Look up each component in current directory
 Return final sector
 Error if component doesn't exist
 Handle /
 Handle repeated / if desired
Sprint 6 — Lifecycle
Create

FileNode.create():

 Validate parent
 Find free node sector
 Mark node 01
 Save node
 Add dirent to parent

DirNode.create():

 Same basic process
 Set directory flag
 Add dirent
Delete file
 Remove parent dirent
 Free node sector
 Free direct data sectors
 Walk extent chain
 Free extent sectors
 Free extent data sectors
 Set allocation bits to 00
Delete directory
 Read all children
 Delete each child recursively
 Free directory's data
 Free directory node
 Remove its parent dirent
Rename
 Validate new name
 Check duplicate in parent
 Update child's filename/extension
 Update cached parent dirent
 Save both
Truncate
Shrinking first
 Reduce logical size
 Free unnecessary direct sectors
 Free unnecessary extent data
 Remove empty extents
 Update length
 Update size
Growing
 Reuse write_data() machinery
 New bytes should be zero-filled
Sprint 7 — Integration test

Make one script:

test_gosfs.py
Format
 Create fresh image
 Format filesystem
 Verify header
 Verify root
Directories
 Create /home
 Create /home/test
 Create /home/test/stuff
Files
 Create empty file
 Create small file
 Create large file
 Create file with long filename
 Write contents
Read/write
 Read
 Overwrite
 Append
 Write past EOF
 Verify zero filling
Directory operations
 List
 Rename
 Lookup
 Remove
Deletion
 Delete file
 Delete empty directory
 Delete non-empty directory
 Verify recursive deletion
 Verify freed sectors can be reused
Assertions

Don't just print results.

Use:

assert actual == expected

The entire test should end with something like:

ALL TESTS PASSED
Sprint 8 — FUSE read-only

Only start this once Sprint 7 passes.

Implement the FUSE callbacks:

getattr(path)
 Resolve path
 Load node
 Return file metadata
 Directory gets directory mode
 File gets regular-file mode
 Return size
readdir(path)
 Resolve directory
 Read dirents
 Return .
 Return ..
 Return children
open(path, ...)
 Resolve path
 Verify it is a file
 Reject writes for now
read(path, size, offset, ...)
 Resolve file
 node.read(offset, size)
 Return bytes
Mount test
mount
 ↓
ls
 ↓
ls -l
 ↓
cat file
 ↓
find
 Browse directories
 Read files
 Verify sizes
 Verify contents

No writes yet.

Sprint 9 — FUSE write-side

Implement callbacks one at a time.

create
 Resolve parent
 Create FileNode
 Add dirent
mkdir
 Resolve parent
 Create DirNode
 Add dirent
write
 Resolve file
 Call write_data()
 Return number of bytes written
truncate
 Resolve file
 Call filesystem truncate()
unlink
 Resolve file
 Delete file
rmdir
 Resolve directory
 Verify directory is empty, or match whatever deletion semantics you decide for FUSE
 Delete directory
rename
 Resolve source
 Resolve destination parent
 Update filesystem structures
Real shell tests
touch test.txt
echo hello > test.txt
cat test.txt
echo world >> test.txt
cat test.txt

mkdir test
mv test.txt test/
cat test/test.txt

mv test/test.txt renamed.txt
rm renamed.txt
rmdir test
Sprint 10 — Stress + persistence

This is basically the final torture test.

Large files
 1 KB
 10 KB
 100 KB
 1 MB
 Multiple extents
 Multiple extent chains
Directory stress
 10 files
 100 files
 1,000 files if practical
 Force direct-range growth
 Force extent growth
 Delete entries from the middle
 Add entries after deletion
 Verify compaction
Filename limits
 255-byte filename
 15-byte extension
 255 + 15 combined
 Names containing multiple .
 No extension
 Duplicate names rejected
Persistence

This one is really important:

mount
 ↓
create files
 ↓
write data
 ↓
unmount
 ↓
close disk
 ↓
new Python process
 ↓
open disk.img
 ↓
mount again
 ↓
verify everything
 Header survives
 Root survives
 Nodes survive
 Dirents survive
 Extents survive
 Allocation bitmap survives
 File contents survive
Corruption / validation
 Invalid magic rejected
 Invalid version rejected
 Invalid node sector rejected
 Invalid extent pointer detected
 Invalid parent detected
 Invalid dirent detected
 Extent loops detected
 Invalid allocation state detected
One thing I'd add to your plan

Before Sprint 2, I'd make a tiny "Sprint 0 — API cleanup" because your current code has enough inconsistencies that it'll make the later sprints painful.

Sprint 0 — Stabilize the internal API
 Decide whether methods are save() or write()
 Decide whether inline_space() is the official name
 Decide whether length means number of data sectors
 Decide that data means inline data only
 Make every node have:
 load(sector)
 create(...)
 save()
 Make sector explicit on every loaded/created node
 Make allocation responsibilities explicit:
 node allocation → 01
 extent allocation → 10
 data allocation → 11
 Remove test code from GOSFS.__init__
 Make formatting separate from mounting/opening

That last one is especially useful:

GOSFS.format()

should create a new filesystem, while:

GOSFS()

should simply open an existing one.

Right now your GOSFS.__init__() is doing both filesystem opening and test/setup work, which will become a headache once FUSE starts opening the image."""

import GOSFS_IO
import struct


def is_sector_free(sector: int):
	if sector == 0:
		return False

	if sector < 0:
		raise ValueError("sector cannot be negative")

	superblock_index = (sector - 1) // 512
	relative_sector = (sector - 1) % 512

	superblock_sector = superblock_index * 512 + 1
	superblock = GOSFSSuperblockNode(superblock_sector)

	return superblock.is_free(relative_sector)

def find_free_sector():
	for superblock_index in range(header.super_blocks_used):
		superblock_sector = superblock_index * 512 + 1
		superblock = GOSFSSuperblockNode(superblock_sector)

		relative_sector = superblock.find_free_sector()

		if relative_sector != None:
			return superblock_sector + relative_sector

	raise IOError("No free sectors")

def grow_range(node, additional_bytes: int) -> int:
	added = 0
	while added < additional_bytes:
		next_sector = node.sector + 1 + node.length
		if not is_sector_free(next_sector):
			break
		GOSFSSuperblockNode(((next_sector - 1) // 512) * 512 + 1).set(
			(next_sector - 1) % 512, 0b11
		)
		node.length += 1
		added += 512
	if added:
		node.save()
	return added

class GOSFSHeaderNode:
	#! little endian
	#! 8b, 1b, 8b, 8b
	FORMAT = "<8sHHQQ"
	SIZE = struct.calcsize(FORMAT)

	def __init__(self, no_of_super_blocks:int =1, super_blocks_used:int =0, root_sector:int =0):
		self.magic = b"GOSFSG_s"
		self.version = 1
		self.no_of_super_blocks = no_of_super_blocks
		self.super_blocks_used = super_blocks_used
		self.root_sector = root_sector

	def pack(self):
		data = struct.pack(
			GOSFSHeaderNode.FORMAT,
			self.magic,
			self.version,
			self.no_of_super_blocks,
			self.super_blocks_used,
			self.root_sector,
		)
		return data + bytes(512-len(data))

	@classmethod
	def unpack(cls, data):
		if len(data) != 512:
			raise ValueError("header must be exactly 512 bytes")

		magic, version, no_of_super_blocks, super_blocks_used, root_sector = struct.unpack(
			cls.FORMAT, data[: cls.SIZE]
		)

		header = cls(no_of_super_blocks, super_blocks_used, root_sector)
		header.magic = magic
		header.version = version

		return header

class GOSFSSuperblockNode:
	def __init__(self, sector: int|None = None):
		if sector == None:
			# * Get new superblock address
			self.sector = header.super_blocks_used * 512 + 1
			self.allocation = bytearray(512)
			self._set(0, 0b11)
			disk.write_sector(self.sector, self.allocation)
			header.super_blocks_used += 1
			disk.write_sector(0, header.pack())

		else:
			#! Superblocks exist at every 512 sectors starting at 1
			if (sector - 1) % 512 != 0:
				raise ValueError("sector is not a superblock")

			self.sector = sector
			self.allocation = bytearray(disk.read_sector(sector))

	def is_free(self, relative_sector: int):
		if relative_sector == 0:
			return False
		byte_index = relative_sector // 4
		bit_offset = (relative_sector % 4) * 2
		mode = (self.allocation[byte_index] >> bit_offset) & 0b11
		return mode == 0b00

	def _set(self, relative_sector: int, mode: int):
		if not 0b00 <= mode <= 0b11:
			raise ValueError(
				f"invalid mode {mode}; "
				"valid modes are 0b00(unused), "
				"0b01(file/folder), "
				"0b10(extent), "
				"0b11(generic data)"
			)

		if not 0 <= relative_sector < 512:
			raise ValueError("relative sector must be between 0 and 511")

		byte_index = relative_sector // 4
		bit_offset = (relative_sector % 4) * 2

		self.allocation[byte_index] &= ~(0b11 << bit_offset)
		self.allocation[byte_index] |= (mode & 0b11) << bit_offset

	def set(self, relative_sector: int, mode: int = 0b11):
		#! Sector 0 belongs to the superblock itself
		if relative_sector == 0:
			raise ValueError(
				"you are not allowed to change the superblock's own sector"
			)

		self._set(relative_sector, mode)

		disk.write_sector(self.sector, self.allocation)

	def find_free_sector(self):
		for relative_sector in range(1, 512):
			byte_index = relative_sector // 4
			bit_offset = (relative_sector % 4) * 2

			mode = (
				self.allocation[byte_index] >> bit_offset
			) & 0b11

			if mode == 0b00:
				return relative_sector

		return None

class GOSFSFileNode:
	@classmethod
	def load(cls, sector: int):
		if sector == 0:
			raise ValueError("sector cannot be the filesystem header")

		raw = disk.read_sector(sector)
		parent = struct.unpack("<Q", raw[0:8])[0]
		flags = raw[8]
		filename_len = raw[9]
		pos = 10
		filename = raw[pos : pos + filename_len]
		pos += filename_len
		extension_len = raw[pos]
		pos += 1
		extension = raw[pos : pos + extension_len]
		pos += extension_len
		encoding = raw[pos : pos + 8]
		pos += 8
		size = struct.unpack("<Q", raw[pos : pos + 8])[0]
		pos += 8
		length = struct.unpack("<Q", raw[pos : pos + 8])[0]
		pos += 8
		extent = struct.unpack("<Q", raw[pos : pos + 8])[0]
		pos += 8
		data = raw[pos:]
		node = cls(
			parent, flags, filename_len,
			filename, extension_len, extension,
			encoding, size, length,
			extent, data,
		)
		node.sector = sector
		return node

	@classmethod
	def create(
		cls, parent, flags, filename, extension, encoding, size, length, extent, data
	):
		if parent == 0:
			raise ValueError("parent cannot be header")
		if (parent - 1) % 512 == 0:
			raise ValueError("parent cannot be a superblock")
		if flags == 0b00000001:
			raise ValueError(f"{bin(flags)} not valid for files")
		if len(encoding) != 8:
			raise ValueError("encoding must be exactly 8 bytes")
		node = cls(
			parent,
			flags,
			len(filename),
			filename.encode("ascii"),
			len(extension),
			extension.encode("ascii"),
			encoding,
			size,
			length,
			extent,
			data,
		)
		if node.filename_len > 255:
			raise ValueError("max size for filename is 255")
		if node.extension_len > 15:
			raise ValueError("max size for file extension is 15")

		node.sector = find_free_sector()

		GOSFSSuperblockNode(((node.sector - 1) // 512) * 512 + 1).set(
			(node.sector - 1) % 512, 0b01
		)
		return node

	def __init__(self, parent, flags, filename_len, filename, extension_len,
				extension, encoding, size, length, extent, data):
		self.parent = parent
		self.flags = flags
		self.filename_len = filename_len
		self.filename = filename
		self.extension_len = extension_len
		self.extension = extension
		self.encoding = encoding
		self.size = size
		self.length = length
		self.extent = extent
		self.data = data
		self.FORMAT = f"<QBB{self.filename_len}sB{self.extension_len}s8sQQQ"

	# helpers
	def header_size(self):
		return 43 + self.filename_len + self.extension_len

	def inline_space(self):
		return 512 - self.header_size()

	def full_name(self):
		return f"{self.filename}.{self.extension}"

	def save(self):
		data = struct.pack(
			self.FORMAT,
			self.parent, self.flags, self.filename_len, self.filename,
			self.extension_len, self.extension, self.encoding,
			self.size, self.length, self.extent,
		)
		data += self.data[:self.inline_space()]
		data += bytes(512 - len(data))
		disk.write_sector(self.sector, data)

	def read(self, offset: int, size: int):
		end = min(offset + size, self.size)
		if offset >= end:
			return b""

		chunks = [self.data[:self.inline_space()]]

		for relative_sector in range(self.length):
			chunks.append(disk.read_sector(self.sector + 1 + relative_sector))

		extent_sector = self.extent
		while extent_sector:
			extent = GOSFSExtentNode.load(extent_sector)
			chunks.append(extent.data[:extent.inline_space()])
			for relative_extent_sector in range(extent.length):
				chunks.append(disk.read_sector(extent_sector + 1 + relative_extent_sector))
			extent_sector = extent.extent

		full = b"".join(chunks)
		return full[offset:end]

	def write_data(self, offset: int, data: bytes):
		end = offset + len(data)
		new_size = max(self.size, end)

		current = bytearray(self.read(0, self.size))
		if offset > self.size:
			current.extend(bytes(offset - self.size))
		current[offset:end] = data

		self._ensure_capacity(new_size)
		self._distribute(bytes(current))
		self.size = new_size
		self.save()

	def _ensure_capacity(self, needed: int):
		have = self.inline_space() + self.length * 512

		if have >= needed:
			return

		have += grow_range(self, needed - have)
		if have >= needed:
			return

		if self.extent == 0:
			last = GOSFSExtentNode.create(parent=self.sector)
			self.extent = last.sector
			self.save()
			have += last.inline_space()
		else:
			last = GOSFSExtentNode.load(self.extent)
			have += last.inline_space() + last.length * 512
			while last.extent != 0:
				last = GOSFSExtentNode.load(last.extent)
				have += last.inline_space() + last.length * 512

		have += last.inline_space()

		while have < needed:
			have += grow_range(last, needed - have)
			if have >= needed:
				return

			new_ext = GOSFSExtentNode.create(parent=last.sector)
			last.extent = new_ext.sector
			last.save()
			last = new_ext
			have += last.inline_space()

	def _distribute(self, data):
		inline_space = self.inline_space()
		self.data = data[:inline_space]
		completed = inline_space

		if completed >= len(data):
			return

		for cur in range(self.length):
			if completed >= len(data):
				return
			disk.write_sector(self.sector + 1 + cur, data[completed:completed + 512])
			completed += 512

		if completed >= len(data):
			return

		extent_sector = self.extent
		while extent_sector:
			if completed >= len(data):
				return
			extent = GOSFSExtentNode.load(extent_sector)

			extent.data = data[completed:completed + extent.inline_space()]
			extent.save()
			completed += extent.inline_space()

			for cur in range(extent.length):
				if completed >= len(data):
					break
				disk.write_sector(extent.sector + 1 + cur, data[completed:completed + 512])
				completed += 512

			extent_sector = extent.extent

class GOSFSDirectoryEntryNode:
	def __init__(self, child_sector, name_len, name, ext_len, ext):
		self.child_sector = child_sector
		self.name_len = name_len
		self.name = name
		self.ext_len = ext_len
		self.ext = ext

	def pack(self):
		return struct.pack(f"<QB{self.name_len}sB{self.ext_len}s", self.child_sector, self.name_len, self.name, self.ext_len, self.ext)

class GOSFSDirectoryNode:
	def __init__(self, parent, flags, filename_len, filename, extension_len, extension, length, extent, entries):
		self.parent = parent
		self.flags = flags
		self.filename_len = filename_len
		self.filename = filename
		self.extension_len = extension_len
		self.extension = extension
		self.length = length
		self.extent = extent
		self.entries = []
		for entry in entries:
			self.entries.append(GOSFSDirectoryEntryNode(*entry))
		self.FORMAT = f"<QBB{filename_len}sB{extension_len}sQQ"

	def pack(self):
		data = struct.pack(self.FORMAT, self.parent, self.flags, self.filename_len, self.filename, self.extension_len, self.extension, self.length, self.extent)
		for entry in self.entries:
			data += entry.pack()
		return data

class GOSFSExtentNode:
	FORMAT = "<QBQQ"
	HEADER_SIZE = struct.calcsize(FORMAT)  # 25

	@classmethod
	def load(cls, sector):
		if sector == 0:
			raise ValueError("Sector cannot be the filesystem header")

		extent = disk.read_sector(sector)
		header_size = GOSFSExtentNode.HEADER_SIZE
		parent, flags, length, extent_node = struct.unpack(GOSFSExtentNode.FORMAT, extent[:header_size])
		return cls(parent, flags, length, extent_node, extent[header_size:], sector)

	@classmethod
	def create(cls, parent, flags=0, length=0, extent=0, data=b""):
		node = cls(parent, flags, length, extent, data)
		node.sector = find_free_sector()
		GOSFSSuperblockNode(((node.sector-1)//512)*512+1).set((node.sector-1)%512, 0b10)
		node.save()
		return node

	def __init__(self, parent, flags, length, extent, data, sector):
		self.parent = parent
		self.flags = flags
		self.length = length
		self.extent = extent
		self.data = data
		self.sector = sector

	# helpers
	def header_size(self):
		return self.HEADER_SIZE

	def inline_space(self):
		return 512 - self.header_size()  # 487

	def save(self):
		header = struct.pack(GOSFSExtentNode.FORMAT, self.parent, self.flags, self.length, self.extent)
		data = header + self.data[:self.inline_space()]
		data += bytes(512 - len(data))
		disk.write_sector(self.sector, data)

class GOSFS:
    def __init__(self):
        global disk, header
        disk = GOSFS_IO.Disk()
        header = GOSFSHeaderNode.unpack(disk.read_sector(0))
        if header.magic == b"GOSFSG_s":
            pass
        elif header.magic == b"\x00" * 8:
            print("empty header detected, initializing new GOSFS instance")
            header = GOSFSHeaderNode()
            disk.write_sector(0, header.pack())
            GOSFSSuperblockNode()
        else:
            print("error")
        self.disk = disk
        self.header = header

GOSFS()

