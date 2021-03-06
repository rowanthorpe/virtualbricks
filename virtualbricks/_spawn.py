import os
from twisted.internet.utils import getProcessOutput, getProcessOutputAndValue


def _abspath_exe(path, executable, return_relative=True):
    if '/' in executable:
        if os.access(executable, os.X_OK) or return_relative:
            return executable
        else:
            return None
    if isinstance(path, basestring) and path != '':
        abspath = os.path.join(path, executable)
        if os.access(abspath, os.X_OK):
            return abspath
        elif return_relative:
            return executable
        else:
            return None
    paths = os.environ.get('PATH', '.').split(':')
    for path in paths:
        if os.access(os.path.join(path, executable), os.X_OK):
            return os.path.join(path, executable)
    if return_relative:
        # cannot find executable, return the relative filename
        return executable


def getQemuOutput(executable, args=(), env={}, path=None, reactor=None,
                  errortoo=0):
    exe = abspath_qemu(executable)
    return getProcessOutput(exe, args, env, path, reactor, errortoo)


def getQemuOutputAndValue(executable, args=(), env={}, path=None, reactor=None):
    exe = abspath_qemu(executable)
    return getProcessOutputAndValue(exe, args, env, path, reactor)


def getVdeOutput(executable, args=(), env={}, path=None, reactor=None,
                 errortoo=0):
    exe = abspath_vde(executable)
    return getProcessOutput(exe, args, env, path, reactor, errortoo)


def abspath_vde(executable, return_relative=True):
    from virtualbricks import settings

    return _abspath_exe(settings.get('vdepath'), executable, return_relative)


def abspath_qemu(executable, return_relative=True):
    from virtualbricks import settings

    return _abspath_exe(settings.get('qemupath'), executable, return_relative)
