import weakref

from asdf import constants

from . import io as bio


class ReadBlock:
    def __init__(self, offset, fd, memmap, lazy_load, validate_checksum, header=None, data_offset=None, data=None):
        self.offset = offset  # after magic
        self._fd = weakref.ref(fd)
        self._header = header
        self.data_offset = data_offset
        self._data = data
        self._cached_data = None
        # TODO alternative to passing these down?
        self.memmap = memmap
        self.lazy_load = lazy_load
        self.validate_checksum = validate_checksum
        if not lazy_load:
            self.load()

    @property
    def loaded(self):
        return self._data is not None

    def load(self):
        if self.loaded:
            return
        fd = self._fd()
        if fd is None or fd.is_closed():
            msg = "Attempt to load block from closed file"
            raise OSError(msg)
        position = fd.tell()
        _, self._header, self.data_offset, self._data = bio.read_block(
            fd, offset=self.offset, memmap=self.memmap, lazy_load=self.lazy_load
        )
        fd.seek(position)

    @property
    def data(self):
        if not self.loaded:
            self.load()
        if callable(self._data):
            data = self._data()
        else:
            data = self._data
        if self.validate_checksum:
            checksum = bio.calculate_block_checksum(data)
            if checksum != self._header["checksum"]:
                msg = f"Block at {self.offset} does not match given checksum"
                raise ValueError(msg)
            # only validate data the first time it's read
            self.validate_checksum = False
        return data

    @property
    def cached_data(self):
        if self._cached_data is None:
            self._cached_data = self.data
        return self._cached_data

    @property
    def header(self):
        if not self.loaded:
            self.load()
        return self._header


def read_blocks_serially(fd, memmap=False, lazy_load=False, validate_checksums=False, after_magic=False):
    blocks = []
    buff = b""
    magic_len = len(constants.BLOCK_MAGIC)
    while True:
        # the expectation is that this will begin PRIOR to the block magic
        # read 4 bytes
        if not after_magic:
            buff += fd.read(magic_len - len(buff))
            if len(buff) < magic_len:
                # we are done, there are no more blocks and no index
                # TODO error? we shouldn't have extra bytes, the old code allows this
                break

        if buff == constants.INDEX_HEADER[:magic_len]:
            # we hit the block index, which is not useful here
            break

        if after_magic or buff == constants.BLOCK_MAGIC:
            # this is another block
            offset, header, data_offset, data = bio.read_block(fd, memmap=memmap, lazy_load=lazy_load)
            blocks.append(
                ReadBlock(
                    offset, fd, memmap, lazy_load, validate_checksums, header=header, data_offset=data_offset, data=data
                )
            )
            if blocks[-1].header["flags"] & constants.BLOCK_FLAG_STREAMED:
                # a file can only have 1 streamed block and it must be at the end so we
                # can stop looking for more blocks
                break
            buff = b""
            after_magic = False
        else:
            if len(blocks) or buff[0] != 0:
                # if this is not the first block or we haven't found any
                # blocks and the first byte is non-zero
                msg = f"Invalid bytes while reading blocks {buff}"
                raise OSError(msg)
            # this is the first block, allow empty bytes before block
            buff = buff.strip(b"\0")
    return blocks


def read_blocks(fd, memmap=False, lazy_load=False, validate_checksums=False, after_magic=False):
    if not lazy_load or not fd.seekable():
        # load all blocks serially
        return read_blocks_serially(fd, memmap, lazy_load, validate_checksums, after_magic)

    # try to find block index
    starting_offset = fd.tell()
    index_offset = bio.find_block_index(fd, starting_offset)
    if index_offset is None:
        # if failed, load all blocks serially
        fd.seek(starting_offset)
        return read_blocks_serially(fd, memmap, lazy_load, validate_checksums, after_magic)

    # setup empty blocks
    try:
        block_index = bio.read_block_index(fd, index_offset)
    except OSError:
        # failed to read block index, fall back to serial reading
        fd.seek(starting_offset)
        return read_blocks_serially(fd, memmap, lazy_load, validate_checksums, after_magic)
    # skip magic for each block
    magic_len = len(constants.BLOCK_MAGIC)
    blocks = [ReadBlock(offset + magic_len, fd, memmap, lazy_load, validate_checksums) for offset in block_index]
    try:
        # load first and last blocks to check if the index looks correct
        for index in (0, -1):
            fd.seek(block_index[index])
            buff = fd.read(magic_len)
            if buff != constants.BLOCK_MAGIC:
                msg = "Invalid block magic"
                raise OSError(msg)
            blocks[index].load()
    except (OSError, ValueError):
        fd.seek(starting_offset)
        return read_blocks_serially(fd, memmap, lazy_load, after_magic)
    return blocks
