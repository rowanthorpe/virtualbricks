# -*- test-case-name: virtualbricks.tests.test_tools -*-
# Virtualbricks - a vde/qemu gui written in python and GTK/Glade.
# Copyright (C) 2013 Virtualbricks team

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.


import os
import sys
import errno
import random
import re
import functools
import tempfile
import struct

from virtualbricks import log

from twisted.internet import utils

logger = log.Logger()
ksm_error = log.Event("Can not change ksm state. (failed command: {cmd})")


def random_mac():
    random.seed()
    return "00:aa:{0:02x}:{1:02x}:{2:02x}:{3:02x}".format(
        random.getrandbits(8), random.getrandbits(8), random.getrandbits(8),
        random.getrandbits(8))

RandMac = random_mac
MAC_RE = re.compile(r"^([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$")

def mac_is_valid(mac):
    return bool(MAC_RE.match(mac))


def synchronize(func, lock):
    @functools.wraps(func)
    def wrapper(*args, **kwds):
        with lock:
            return func(*args, **kwds)
    return wrapper


def synchronize_with(lock):
    def wrap(func):
        return synchronize(func, lock)
    return wrap


def stack_trace():
    out = []
    f = sys._getframe(1)
    while f:
        out.append("{0.f_code.co_filename}:{0.f_lineno}".format(f))
        f = f.f_back
    return "\n".join(out)


def check_missing(path, files):
    return [f for f in files if not os.access(os.path.join(path, f), os.X_OK)]

vde_bins = ["vde_switch", "vde_plug", "vde_cryptcab", "dpipe", "vdeterm",
    "vde_plug2tap", "wirefilter"]

qemu_bins = ["qemu", "kvm", "qemu-system-arm", "qemu-system-cris",
    "qemu-system-i386", "qemu-system-m68k", "qemu-system-microblaze",
    "qemu-system-mips", "qemu-system-mips64", "qemu-system-mips64el",
    "qemu-system-mipsel", "qemu-system-ppc", "qemu-system-ppc64",
    "qemu-system-ppcemb", "qemu-system-sh4", "qemu-system-sh4eb",
    "qemu-system-sparc", "qemu-system-sparc64", "qemu-system-x86_64",
    "qemu-img"]

def bin2brick(bin_name):

    brick_bin = {'Switch': 'vde_switch',
            'Wire': 'vde_plug',
            'Wirefilter': 'wirefilter',
            'Tap': 'vde_plug2tap',
            'TunnelConnect': 'vde_cryptcab',
            'TunnelListen': 'vde_cryptcab',
            'Capture': 'vde_pcapplug',
    }

    brick_list = []
    if bin_name in qemu_bins:
        brick_list = ['Qemu']
    else:
        for i in brick_bin.iterkeys():
            if brick_bin[i] == bin_name:
                brick_list.append(i)

    return brick_list

def check_missing_vde(path):
    return check_missing(path, vde_bins)

def check_missing_qemu(path):
    missing = check_missing(path, qemu_bins)
    return missing, sorted(set(qemu_bins) - set(missing))

def check_kvm(path):
    if not os.access(os.path.join(path, "kvm"), os.X_OK):
        return False
    if not os.access("/sys/class/misc/kvm", os.X_OK):
        return False
    return True


def check_ksm():
    try:
        with open("/sys/kernel/mm/ksm/run") as fp:
            return bool(int(fp.readline()))
    except IOError:
        return False


def _check_cb(exit_code, cmd):
    if exit_code:  # exit state != 0
        logger.error(ksm_error, cmd=cmd)


def enable_ksm(enable, sudo):
    if enable ^ check_ksm():
        cmd = "echo {0:d} > /sys/kernel/mm/ksm/run".format(enable)
        if sudo:
            d = utils.getProcessValue(sudo,
                ["--", "su", "-c", cmd], env=os.environ)
        else:
            d = utils.getProcessValue(os.environ.get("SHELL", "/bin/sh"),
                ["-c", cmd], env=os.environ)
        d.addCallback(_check_cb, cmd)


class Tempfile:

    def __enter__(self):
        self.fd, self.filename = tempfile.mkstemp()
        return self.fd, self.filename

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            os.remove(self.filename)
        except OSError, e:
            if e.errno != errno.ENOENT:
                raise


HEADER_FMT = r">BBBBI"
COW_MAGIC = "MOOO"[::-1]
COW_SIZE = 1024
QCOW_MAGIC = "QFI\xfb"
QCOW_HEADER_FMT = r">QI"


def get_backing_file_from_cow(fp):
    data = fp.read(COW_SIZE)
    return data.rstrip("\x00")

def get_backing_file_from_qcow(fp):
    offset, size = struct.unpack(QCOW_HEADER_FMT, fp.read(12))
    if size == 0:
        return ""
    else:
        fp.seek(offset)
        return fp.read(size)


class UnknowTypeError(Exception):
    pass


def get_backing_file(fp):
    data = fp.read(8)
    m1, m2, m3, m4, version = struct.unpack(HEADER_FMT, data)
    magic = "".join(map(chr, (m1, m2, m3, m4)))
    if magic == COW_MAGIC:
        return get_backing_file_from_cow(fp)
    elif magic == QCOW_MAGIC and version in (1, 2):
        return get_backing_file_from_qcow(fp)
    raise UnknowTypeError()


def backing_files_for(files):
    for file in files:
        try:
            with open(file) as fp:
                yield get_backing_file(fp)
        except UnknowTypeError:
            pass


def fmtsize(size):
    if size < 10240:
        return "{0} B".format(size)
    size /= 1024.0
    for unit in "KB", "MB", "GB":
        if size < 1024:
            return "{0:.1f} {1}".format(size, unit)
        size /= 1024.0
    return "{0:.1f} TB".format(size)


def copyTo(self, destination, followLinks=True):
    """
    Copies self to destination.

    If self doesn't exist, an OSError is raised.

    If self is a directory, this method copies its children (but not
    itself) recursively to destination - if destination does not exist as a
    directory, this method creates it.  If destination is a file, an
    IOError will be raised.

    If self is a file, this method copies it to destination.  If
    destination is a file, this method overwrites it.  If destination is a
    directory, an IOError will be raised.

    If self is a link (and followLinks is False), self will be copied
    over as a new symlink with the same target as returned by os.readlink.
    That means that if it is absolute, both the old and new symlink will
    link to the same thing.  If it's relative, then perhaps not (and
    it's also possible that this relative link will be broken).

    File/directory permissions and ownership will NOT be copied over.

    If followLinks is True, symlinks are followed so that they're treated
    as their targets.  In other words, if self is a link, the link's target
    will be copied.  If destination is a link, self will be copied to the
    destination's target (the actual destination will be destination's
    target).  Symlinks under self (if self is a directory) will be
    followed and its target's children be copied recursively.

    If followLinks is False, symlinks will be copied over as symlinks.

    @param destination: the destination (a FilePath) to which self
        should be copied
    @param followLinks: whether symlinks in self should be treated as links
        or as their targets
    """
    if self.islink() and not followLinks:
        os.symlink(os.readlink(self.path), destination.path)
        return
    # XXX TODO: *thorough* audit and documentation of the exact desired
    # semantics of this code.  Right now the behavior of existent
    # destination symlinks is convenient, and quite possibly correct, but
    # its security properties need to be explained.
    if self.isdir():
        if not destination.exists():
            destination.createDirectory()
        for child in self.children():
            destChild = destination.child(child.basename())
            copyTo(child, destChild, followLinks)
    elif self.isfile():
        writefile = destination.open('w')
        try:
            readfile = self.open()
            try:
                while 1:
                    # XXX TODO: optionally use os.open, os.read and O_DIRECT
                    # and use os.fstatvfs to determine chunk sizes and make
                    # *****sure**** copy is page-atomic; the following is
                    # good enough for 99.9% of everybody and won't take a
                    # week to audit though.
                    chunk = readfile.read(self._chunkSize)
                    writefile.write(chunk)
                    if len(chunk) < self._chunkSize:
                        break
            finally:
                readfile.close()
        finally:
            writefile.close()
    elif not self.exists():
        raise OSError(errno.ENOENT, "No such file or directory")
