# GOSFS

GOSFS is a simple filesystem designed around fixed-size 512-byte sectors, explicit metadata, and linked extents for data that does not fit inside a node.

All multi-byte integer fields are stored little-endian.

## Filesystem Layout

GOSFS uses:

```text
1 block = 1 sector = 512 bytes
```

Sector `0` is the filesystem header.

Superblocks begin at sector `1`.

```text
sector 0
└── filesystem header

sector 1
└── superblock 0

sector 513
└── superblock 1

sector 1025
└── superblock 2

...
```

A superblock describes 512 sectors:

```text
512 sectors × 512 bytes = 262144 bytes
```

The superblock containing sector `N` can therefore be determined from the filesystem layout.

The sector a superblock itself occupies (e.g. sector `1`, `513`, `1025`, ...) is marked `11` (data) in its own bitmap, since the bitmap has no dedicated "superblock" state. Superblock sector addresses are static and computable from `no_of_super_blocks`, so the allocator must exclude them explicitly rather than relying on the bitmap to identify them as superblocks.

## Filesystem Header

The filesystem header occupies the first sector:

```text
fs_super_super_block_t {
    magic
    version
    no_of_super_blocks
    super_blocks_used
    root_sector
    reserved
}
```

Current fields:

| Field                |      Size | Description                                  |
| --------------------- | --------: | --------------------------------------------- |
| `magic`               |   8 bytes | `GOSFSG_s`                                     |
| `version`             |   2 bytes | Filesystem format version(1)                   |
| `no_of_super_blocks`  |   2 bytes | Number of superblocks (uint16)                 |
| `super_blocks_used`   |   8 bytes | Number currently used (uint64)                 |
| `root_sector`         |   8 bytes | Sector address of the root directory's node    |
| `reserved`            | 484 bytes | Reserved                                       |

`super_blocks_used` is a `uint64` (not `uint8`) so it can represent volumes larger than 255 superblocks (~64 MiB) — it must be able to count as high as `no_of_super_blocks`, which is itself a `uint16`.

The header is not governed by a superblock.

The header is also the parent endpoint for the root directory: the root directory's `parent` field points to sector `0`. `root_sector` is what lets the driver locate the root node's own sector on mount, going forward.

## Superblocks

Each superblock describes the allocation state of 512 sectors.

The allocation information uses **2 bits per sector**:

```text
00 = unused / available
01 = file or folder node
10 = extent
11 = data
```

These values describe what the sector is being used for. They are separate from the flags stored inside a node. A sector holding a superblock is marked `11` in its own table (see above); the filesystem header at sector `0` is not covered by any superblock.

For example:

```text
sector 100 → 01
sector 101 → 10
sector 102 → 11
```

means:

```text
100 → file/folder node
101 → extent
102 → data
```

The `11` state is used for data belonging to files, directories, extents, or a superblock's own sector.

The sector-type table requires:

```text
512 × 2 bits = 1024 bits = 128 bytes
```

leaving the remainder of the 512-byte superblock available for other filesystem metadata.

## Nodes

Files and directories are stored as nodes.

Every node has the general structure:

```text
node {
    parent
    metadata
    data / children
    extent
}
```

The node's own sector address identifies the node, so a separate `start_sector` field is not required.

### Parent

`parent` is a `uint64` sector address.

It points to:

* the parent directory for a file or directory;
* the file/directory or previous extent for an extent.

The root directory's parent is the filesystem header (sector `0`).

An entry without a parent is not valid.

### Flags

The first field in `metadata` is `flags`, a `uint8`.

Flags describe the actual type and properties of the node. This is separate from the 2-bit sector state in the superblock.

The node type can be represented in the flags, while additional bits can describe properties such as:

* hidden
* compressed
* invalid link
* other filesystem-specific states

POSIX-style metadata (mode, uid, gid, timestamps) is not part of the current format and is deferred to a later revision.

### Filename and extension encoding

`filename` and `extension` are stored **length-prefixed**, not fixed-width:

```text
filename_len     1 byte   (0–255)
filename         filename_len bytes, ASCII
extension_len    1 byte   (0–15)
extension        extension_len bytes, ASCII
```

The split point between `filename` and `extension` is the **last** `.` in the full name. For example, `archive.tar.gz` stores `filename = "archive.tar"`, `extension = "gz"`. A name with no `.` stores an empty `extension` (`extension_len = 0`).

Because the name fields are variable-length, node headers are **not fixed-size structs** — a node must be parsed sequentially: read `flags`, read `filename_len`, read that many bytes, read `extension_len`, read that many bytes, and only then are the offsets of the remaining fixed-size fields (and the start of inline data/children) known. The same applies in reverse when writing a node.

## Files

A file has the conceptual layout:

```text
file {
    parent
    metadata {
        flags
        filename
        extension
        encoding
        size
        length
    }
    data
    extent
}
```

### File metadata

| Field           |           Size | Description                                                |
| --------------- | --------------: | ----------------------------------------------------------- |
| `flags`         |          1 byte | File type and additional properties                         |
| `filename_len`  |          1 byte | Length of `filename`, 0–255                                 |
| `filename`      | `filename_len` bytes | ASCII, up to the last `.` in the full name              |
| `extension_len` |          1 byte | Length of `extension`, 0–15                                 |
| `extension`     | `extension_len` bytes | ASCII, everything after the last `.`                   |
| `encoding`      |         8 bytes | Describes the file's encoding                                |
| `size`          |         8 bytes | `uint64` — logical file size in bytes                        |
| `length`        |         8 bytes | `uint64` — number of separately allocated data sectors       |

### File node layout

```text
parent            8 bytes
flags             1 byte
filename_len      1 byte
filename          variable (0–255 bytes)
extension_len     1 byte
extension         variable (0–15 bytes)
encoding          8 bytes
size              8 bytes
length            8 bytes
extent            8 bytes
──────────────────────────
fixed overhead   43 bytes  (everything except filename/extension)

header range:  43 bytes (empty name)  →  313 bytes (255+15 char name)
inline data range: 512 - header = 469 bytes (best case) → 199 bytes (worst case)
```

The node's inline `data` is always part of the file's data.

If additional storage is required, `extent` points to the first extent sector. The node's directly allocated data range (when `length > 1`) sits immediately after the node's own sector.

A file's own `filename`/`extension` remain stored on its node even though the parent directory also caches them (see Directories, below). This redundancy is intentional: it keeps the node self-describing for recovery/repair purposes, independent of the parent's cache. It is not used for sibling name-collision checks — that check is done against the parent's cached dirents (see below), not by reading child nodes.

## Directories

Directories use a dedicated layout:

```text
dir {
    parent
    metadata {
        flags
        filename
        extension
        length
    }
    extent
    entries
}
```

Directory nodes carry `filename`/`extension` (same length-prefixed encoding as a file) for the same self-describing reason as files.

A directory's `entries` area contains **dirents** — cached child references — rather than bare sector addresses:

```text
dirent {
    child_sector   uint64  (8 bytes)
    name_len       uint8
    name           name_len bytes
    ext_len        uint8
    ext            ext_len bytes
}
```

Dirents are packed with **no gaps**: the entries area is a contiguous virtual byte stream (inline area → directly-allocated range → extent chain, in that order, the same concatenation model used for file data), and live entries are always packed from its start with no holes between them. `child_sector = 0` is therefore a safe, unambiguous end-of-list marker — since sector `0` is the filesystem header and can never be a real child, and since compaction (below) guarantees no deleted entry is ever left sitting mid-stream, hitting `child_sector = 0` always means "no more entries," never "skip past a deleted one."

**Insertion** appends a new dirent immediately after the current last live entry, growing into a new directly-allocated sector or the extent chain only if the entries area's already-allocated capacity is exhausted.

**Deletion** removes an entry by shifting every entry that follows it left (toward the start of the stream) by the removed entry's byte length, closing the gap immediately — no tombstones are left behind. Because unused capacity only ever accumulates at the very end of the virtual stream (never fragmented in the middle — a consequence of always compacting toward the front), a directory's live-entry length can be found with a single forward scan, and any trailing unused capacity is left allocated rather than freed, to be reused by later inserts.

Caching the name in the parent means `readdir` and lookups scan only the directory's own allocated sectors — no read of any child node is needed to enumerate or search entries. **Renaming a child still touches two places**: the child's own node (`filename`/`extension`, kept for self-description) and the parent's cached dirent (used for lookups) — two separate, non-atomic writes.

The directory's `length` describes the number of separately allocated data sectors used for additional directory data (holding more dirents).

### Directory node layout

```text
parent            8 bytes
flags             1 byte
filename_len      1 byte
filename          variable (0–255 bytes)
extension_len     1 byte
extension         variable (0–15 bytes)
length            8 bytes
extent            8 bytes
──────────────────────────
fixed overhead   27 bytes  (everything except filename/extension)

header range: 27 bytes (empty name) → 297 bytes (255+15 char name)
entries area: 512 - header = 485 bytes (best case) → 215 bytes (worst case)
```

The `entries` area holds as many dirents as fit; since each dirent is itself variable-length (`10` bytes minimum, up to `280` bytes for a maximally long child name), the number of entries per sector is not fixed and must be discovered by scanning.

A directory can therefore have:

```text
directory
├── inline entries (dirents)
├── data range
│   └── additional dirents
└── extent
    └── more dirents
```

A directory cannot contain two entries with the same filename and extension.

The same filename and extension may exist in different directories.

For example:

```text
/home/file.txt
/home/stuff/file.txt
```

is valid because the entries have different parents.

## Extents

Extents provide additional storage when the node's inline data and directly allocated range are not sufficient.

An extent has the layout:

```text
extent {
    parent
    metadata {
        flags
        length
    }
    extent
    data
}
```

### Extent node layout

```text
parent    8 bytes
flags     1 byte
length    8 bytes
extent    8 bytes
────────────────
 header  25 bytes

data = 512 - 25 = 487 bytes
```

An extent occupies one sector.

Its data is stored **immediately after the extent sector**.

For example:

```text
sector 500 → extent
sector 501 → data
sector 502 → data
sector 503 → data
```

If:

```text
length = 3
```

then sectors `501` through `503` are the extent's data.

Therefore allocating an extent with `length = N` requires:

```text
1 extent sector + N consecutive data sectors
```

The extent's `extent` field points to the next extent sector.

```text
extent A
   ↓
extent B
   ↓
extent C
   ↓
0
```

`extent = 0` marks the end of the extent chain. This is a distinct, unambiguous use of `0` from the dirent-area `child_sector = 0` marker above: one ends a *linked list of extent sectors*, the other ends a *packed list of dirents within* whichever sectors are currently allocated.

Since each extent has only one `extent` pointer, extents form a linked list rather than a branching tree.

The `parent` field points backwards:

```text
file
  ↓
extent A
  ↓
extent B
  ↓
extent C
```

So:

```text
extent A.parent = file
extent B.parent = extent A
extent C.parent = extent B
```

## Directory Extents

Directories can also use extents.

For example:

```text
dir
├── entries (dirents)
└── extent
     ↓
   extent
   └── data = more dirents
        ↓
      extent
      └── data = more dirents
```

This allows a directory to contain more child entries than can fit in its node. Since the entries area is read and written as one continuous virtual byte stream, a single dirent may straddle a sector or extent boundary; the driver's stream read/write logic must handle that transparently rather than assuming each dirent fits within one sector.

## Data Allocation

A node can have inline data followed by separately allocated data.

If a contiguous range is available, the node can use it directly. This directly allocated range sits **immediately after the node's own sector**.

For example:

```text
node
length = 4

data sector
data sector
data sector
data sector
```

The actual sectors are determined from the allocation information and the node's stored length.

If enough contiguous sectors cannot be found, an extent can be allocated for another range.

This means files and directories do not require all of their data to be physically contiguous.

## Sector Ownership

The superblock tells the filesystem what a sector contains:

```text
00 → available
01 → file/folder node
10 → extent
11 → data (including a superblock's own sector)
```

The node or extent that references a data sector establishes its ownership.

Data sectors do not need to contain their own parent pointers.

For example:

```text
extent @ 500
length = 3

501 → data
502 → data
503 → data
```

The extent at sector `500` establishes that those sectors belong to it.

## Links

GOSFS links are represented as node entries and directly reference another entry's sector.

A link can point to a file or directory.

A link is therefore based on a direct entry address rather than storing a filesystem path.

If the target is deleted, the link remains but is marked with the invalid flag.

## Reading Data

A file is read conceptually as:

1. Read the node sector.
2. Read its inline `data`.
3. Read its directly allocated data range.
4. If `extent == 0`, stop.
5. Otherwise read the referenced extent.
6. Read the extent's data.
7. Follow its `extent` pointer.
8. Continue until `extent == 0`.
9. Use `size` as the logical file size.

The same extent mechanism can be used by directories to retrieve additional dirents.

## Directories and Paths

A directory contains cached dirents referencing its child entries.

To find a child:

```text
current directory
    ↓
scan dirents (inline → data range → extent chain, as one virtual stream)
    ↓
match on name/extension, stop at the first child_sector == 0
    ↓
child entry sector (from dirent.child_sector)
```

The child entry can then be read directly using the sector address cached in the dirent — no read of the child node is required just to know its name.

The child's `parent` pointer is not required to read the child. It exists to maintain the parent relationship and allow upward traversal or structural operations such as moving entries.

## Deletion

Deletion is recursive.

### File

When a file is deleted:

* its node is marked unused;
* its allocated data sectors are freed;
* its extent chain is recursively freed;
* data belonging to those extents is freed;
* the parent directory's dirent for this file is removed, and every dirent after it is shifted left to close the gap.

### Directory

When a directory is deleted:

* every child is recursively deleted;
* child directories are recursively traversed;
* all descendant data and extents are freed;
* the directory's own data is freed;
* the directory node is marked unused;
* the parent directory's dirent for this directory is removed, and every dirent after it is shifted left to close the gap.

### Link

When a link's target is deleted, the link remains but receives the invalid flag.

## Allocation States

Allocation and freeing use the superblock's 2-bit sector state.

Allocation changes:

```text
00 → 01
```

for a file/folder node,

```text
00 → 10
```

for an extent,

or:

```text
00 → 11
```

for data (including a superblock's own sector).

When the corresponding object is deleted:

```text
01 → 00
10 → 00
11 → 00
```

A node and its associated extents/data therefore have independent sector allocation states.

## Physical Structure

A simplified file with an extent can look like:

```text
file node
├── parent
├── metadata
├── inline data
└── extent ──────────────┐
                         ↓
                    extent sector
                    ├── parent
                    ├── metadata
                    ├── data
                    └── extent ─────┐
                                    ↓
                               extent sector
                               ├── parent
                               ├── metadata
                               ├── data
                               └── extent = 0
```

The extent's data immediately follows its extent sector:

```text
extent
↓
data
data
data
...
```

This provides a simple linked-list mechanism for extending the storage of files and directories without requiring all of their data to be contiguous.