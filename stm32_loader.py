#!/usr/bin/env python

#
# Copyright (C) 2015 Pavel Kirienko <pavel.kirienko@zubax.com>
#

from __future__ import division, absolute_import, print_function, unicode_literals

import sys
import serial
import struct
import time
import logging

from functools import partial, reduce

# Pyton 2.7/3.x compatibility
if sys.version[0] == '2':
    bchr = chr
else:
    bchr = lambda x: bytes([x])

LOGGER_NAME = 'stm32_loader'

ACK = 0x79
NACK = 0x1F

SYNCHRONIZATION_BYTE = 0x7F

WRITE_BLOCK_SIZE = 256
READ_BLOCK_SIZE = 256

CMD_GET = 0x00
CMD_GET_VERSION_AND_PROTECTION_STATUS = 0x01
CMD_GET_ID = 0x02
CMD_READ_MEMORY = 0x11
CMD_GO = 0x21
CMD_WRITE_MEMORY = 0x31
CMD_ERASE = 0x43
CMD_EXTENDED_ERASE = 0x44
CMD_WRITE_PROTECT = 0x63
CMD_WRITE_UNPROTECT = 0x73
CMD_READOUT_PROTECT = 0x82
CMD_READOUT_UNPROTECT = 0x92

DEFAULT_FLASH_ADDRESS = 0x08000000

logger = logging.getLogger(LOGGER_NAME)


class STM32LoaderException(Exception):
    pass


class STM32LoaderTimeoutException(STM32LoaderException):
    pass


class STM32LoaderNACKException(STM32LoaderException):
    pass


class STM32Loader:
    def __init__(self, port, baudrate=None, timeout=None, synchronization_prefix=None):
        baudrate = baudrate or 115200
        timeout = timeout or 1.0
        self.synchronization_prefix = synchronization_prefix or b''
        self.io = serial.Serial(port=port, baudrate=baudrate, parity=serial.PARITY_EVEN, timeout=timeout)

    def close(self):
        self.io.close()

    def _read_bytes(self, num_bytes):
        x = self.io.read(num_bytes)
#        logger.debug('Read: %s', repr(x))
        if len(x) != num_bytes:
            raise STM32LoaderTimeoutException()
        if sys.version[0] == '2':
            return list(map(ord, x))
        else:
            return list(x)

    def _read_byte(self):
        return self._read_bytes(1)[0]

    def _write(self, data):
#        logger.debug('Write: %s', repr(data))
        self.io.write(data)

    def _wait_for_ack(self):
        x = self._read_byte()
        if x == NACK:
            raise STM32LoaderNACKException()
        if x != ACK:
            raise STM32LoaderException('Invalid response while waiting for ACK: 0x%02x' % x)

    def synchronize(self, skip_prefix=False):
        self.io.flushInput()
        if self.synchronization_prefix and not skip_prefix:
            self._write(self.synchronization_prefix)
            time.sleep(1)
        self._write(bchr(SYNCHRONIZATION_BYTE))
        time.sleep(1)
        self.io.flushInput()

    def generic_execute_and_confirm(self, cmd):
        logger.debug('Executing 0x%02x', cmd)
        self._write(bchr(cmd))
        self._write(bchr(cmd ^ 0xFF))
        self._wait_for_ack()

    def get(self):
        self.generic_execute_and_confirm(CMD_GET)
        response_length = self._read_byte()
        bl_version = self._read_byte()
        available_commands = self._read_bytes(response_length)
        self._wait_for_ack()
        return {'version': bl_version,
                'commands': available_commands}

    def get_version_and_protection_status(self):
        self.generic_execute_and_confirm(CMD_GET_VERSION_AND_PROTECTION_STATUS)
        bl_version = self._read_byte()
        option_byte_1 = self._read_byte()
        option_byte_2 = self._read_byte()
        self._wait_for_ack()
        return {'version': bl_version,
                'option_bytes': [option_byte_1, option_byte_2]}

    def get_id(self):
        self.generic_execute_and_confirm(CMD_GET_ID)
        response_length = self._read_byte()
        if response_length != 1:
            raise STM32LoaderException('GET ID: Unexpected number of bytes')
        id_msb = self._read_byte()
        id_lsb = self._read_byte()
        self._wait_for_ack()
        return (id_msb << 8) | id_lsb

    def write_unprotect(self):
        self.generic_execute_and_confirm(CMD_WRITE_UNPROTECT)
        self._wait_for_ack()

    def readout_unprotect(self):
        self.generic_execute_and_confirm(CMD_READOUT_UNPROTECT)
        self._wait_for_ack()

    def _encode_address_with_checksum(self, address):
        address_bytes = list(struct.pack('>I', address))
        if sys.version[0] == '2':
            address_bytes = list(map(ord, address_bytes))
        address_bytes.append(reduce(lambda a, x: a ^ x, address_bytes))
        return b''.join(map(bchr, address_bytes))

    def read_memory(self, start_address, length):
        self.generic_execute_and_confirm(CMD_READ_MEMORY)

        # Address
        address_bytes = self._encode_address_with_checksum(start_address)
        self._write(address_bytes)
        self._wait_for_ack()

        # Length
        encoded_length = min(length, 256) - 1
        self._write(bchr(encoded_length))
        self._write(bchr(encoded_length ^ 0xFF))
        self._wait_for_ack()

        # Read data
        return b''.join(map(bchr, self._read_bytes(length)))

    def write_memory(self, start_address, data):
        if len(data) > 256 or len(data) == 0 or len(data) % 4 != 0:
            raise STM32LoaderException('Invalid data length')

        self.generic_execute_and_confirm(CMD_WRITE_MEMORY)

        # Address
        address_bytes = self._encode_address_with_checksum(start_address)
        self._write(address_bytes)
        self._wait_for_ack()

        # Length, no checksum, no ACK
        encoded_length = len(data) - 1
        self._write(bchr(encoded_length))

        # Data
        if sys.version[0] == '2':
            checksum = reduce(lambda a, x: a ^ ord(x), data, encoded_length)
        else:
            checksum = reduce(lambda a, x: a ^ x, data, encoded_length)
        self._write(data)
        self._write(bchr(checksum))
        self._wait_for_ack()

    def global_erase(self):
        self.generic_execute_and_confirm(CMD_ERASE)
        self._write(b'\xFF\x00')
        self._wait_for_ack()

    def extended_erase(self):
        self.generic_execute_and_confirm(CMD_EXTENDED_ERASE)
        self._write(b'\xFF\xFF\x00')
        self._wait_for_ack()

    def go(self, start_address):
        self.generic_execute_and_confirm(CMD_GO)
        address_bytes = self._encode_address_with_checksum(start_address)
        self._write(address_bytes)
        self._wait_for_ack()

    def read_memory_blocks(self, start_address, length, progress_report_callback=None):
        progress_report_callback = progress_report_callback or (lambda x: None)

        original_length = length
        offset = 0
        output = b''

        while length > READ_BLOCK_SIZE:
            output += self.read_memory(start_address + offset, READ_BLOCK_SIZE)
            length -= READ_BLOCK_SIZE
            offset += READ_BLOCK_SIZE
            progress_report_callback(offset / float(original_length))

        if length > 0:
            output += self.read_memory(start_address + offset, length)

        progress_report_callback(1.0)
        return output

    def write_memory_blocks(self, start_address, data, progress_report_callback=None):
        progress_report_callback = progress_report_callback or (lambda x: None)

        length = len(data)
        offset = 0

        while length > WRITE_BLOCK_SIZE:
            self.write_memory(start_address + offset, data[offset:offset + WRITE_BLOCK_SIZE])
            length -= WRITE_BLOCK_SIZE
            offset += WRITE_BLOCK_SIZE
            progress_report_callback(offset / float(len(data)))

        if length > 0:
            self.write_memory(start_address + offset, data[offset:offset + length])

        progress_report_callback(1.0)


def load(port,
        binary_image,
        load_address=None,
        progress_report_callback=None,
        readout_unprotect=False,
        write_unprotect=False,
        go=True,
        **loader_arguments):
    # Argument validation
    progress_report_callback = progress_report_callback or (lambda _a, _b: None)
    load_address = load_address or DEFAULT_FLASH_ADDRESS
    while len(binary_image) % 4 != 0:
        binary_image += b'\xFF'

    # Initialization
    progress_report_callback('Synchronization', None)
    loader = STM32Loader(port, **loader_arguments)
    try:
        # First attempt to synchronize
        try:
            loader.synchronize(skip_prefix=False)
        except Exception:
            pass

        # Trying a command; if it fails, trying to resync without prefix
        for _ in range(3):
            try:
                loader.get()
                break
            except Exception:
                logger.debug('Resynchronizing...')
                loader.synchronize(skip_prefix=True)

        # General info
        var_get = loader.get()

        logger.info('Target commands: %s', map(lambda x: '0x%.2x ' % x, var_get['commands']))
        logger.info('Target info: %s', loader.get_version_and_protection_status())
        logger.info('Target ID: 0x%x', loader.get_id())

        # Target preparation
        progress_report_callback('Configuring target', None)

        if readout_unprotect:
            loader.readout_unprotect()
            loader.synchronize()        # Previous command generates system reset

        if write_unprotect:
            loader.write_unprotect()
            loader.synchronize()        # Previous command generates system reset

        if CMD_ERASE in var_get['commands']:
            loader.global_erase()
        else:
            loader.extended_erase()

        # Write
        write_reporter = partial(progress_report_callback, 'Writing image')
        loader.write_memory_blocks(load_address, binary_image, progress_report_callback=write_reporter)

        # Verification
        verification_reporter = partial(progress_report_callback, 'Verification')
        readback = loader.read_memory_blocks(load_address, len(binary_image),
                progress_report_callback=verification_reporter)
        if readback != binary_image:
            raise STM32LoaderException('Verification failed')

        # Run programm
        if go:
            loader.go(load_address)

    finally:
        loader.close()


if __name__ == "__main__":
    logging.basicConfig(stream=sys.stderr, level=logging.DEBUG, format='%(message)s')

    PORT = sys.argv[1]

    if 1:
        FILE = sys.argv[2]
        with open(FILE, 'rb') as f:
            binary = f.read()
        print('Loading "%s" [%.2f KB] via %s' % (FILE, len(binary) / 1024., PORT))
        load(PORT, binary)

    else:
        loader = STM32Loader(PORT)
        loader.synchronize()
        print(loader.get())
        print(loader.get_version_and_protection_status())
        print(loader.get_id())
        loader.global_erase()
        print(repr(loader.read_memory_blocks(0x08000000, 1000, progress_report_callback=print)))
        loader.write_memory_blocks(0x08000000, b'1234567890' * 100, progress_report_callback=print)
        print(repr(loader.read_memory_blocks(0x08000000, 1000, progress_report_callback=print)))

