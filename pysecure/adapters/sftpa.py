import logging

from datetime import datetime
from os import SEEK_SET, SEEK_CUR, SEEK_END, mkdir, unlink, utime
from ctypes import create_string_buffer, cast, c_void_p, c_int, c_char_p, \
                   c_size_t, byref
from collections import deque
from cStringIO import StringIO
from shutil import rmtree
from time import mktime

from pysecure.constants.ssh import SSH_NO_ERROR
from pysecure.constants.sftp import O_RDONLY, O_WRONLY, O_RDWR, O_CREAT, \
                                    O_TRUNC
from pysecure.types import CTimeval
from pysecure.constants import SERVER_RESPONSES
from pysecure.config import DEFAULT_CREATE_MODE, \
                            MAX_MIRROR_LISTING_CHUNK_SIZE, \
                            MAX_MIRROR_WRITE_CHUNK_SIZE
from pysecure.calls.sftpi import c_sftp_get_error, c_sftp_new, c_sftp_init, \
                                 c_sftp_open, c_sftp_write, c_sftp_free, \
                                 c_sftp_opendir, c_sftp_closedir, \
                                 c_sftp_readdir, c_sftp_attributes_free, \
                                 c_sftp_dir_eof, c_sftp_tell, c_sftp_seek, \
                                 c_sftp_read, c_sftp_fstat, c_sftp_rewind, \
                                 c_sftp_close, c_sftp_rename, c_sftp_chmod, \
                                 c_sftp_chown, c_sftp_mkdir, c_sftp_rmdir, \
                                 c_sftp_stat, c_sftp_utimes

from pysecure.exceptions import SftpError
from pysecure.utility import local_recurse

def sftp_get_error(sftp_session_int):
    return c_sftp_get_error(sftp_session_int)

def sftp_get_error_string(code):
    return ('%s [%s]' % (SERVER_RESPONSES[code][1], SERVER_RESPONSES[code][0]))

def _sftp_new(ssh_session_int):
    logging.debug("Creating SFTP session.")

    session = c_sftp_new(ssh_session_int)
    if session is None:
        raise SftpError("Could not create SFTP session.")

    logging.debug("New SFTP session: %s" % (session))
    return session

def _sftp_free(sftp_session_int):
    logging.debug("Freeing SFTP session: %d" % (sftp_session_int))

    c_sftp_free(sftp_session_int)

def _sftp_init(sftp_session_int):
    logging.debug("Initializing SFTP session: %d" % (sftp_session_int))

    result = c_sftp_init(sftp_session_int)
    if result < 0:
        type_ = sftp_get_error(sftp_session_int)
        if type_ >= 0:
            raise SftpError("Could not create SFTP session: %s" % 
                            (sftp_get_error_string(type_)))
        else:
            raise SftpError("Could not create SFTP session. There was an "
                            "unspecified error.")

def _sftp_opendir(sftp_session_int, path):
    logging.debug("Opening directory: %s" % (path))

    sd = c_sftp_opendir(sftp_session_int, path)
    if sd is None:
        type_ = sftp_get_error(sftp_session_int)
        if type_ >= 0:
            raise SftpError("Could not open directory [%s]: %s" % 
                            (path, sftp_get_error_string(type_)))
        else:
            raise SftpError("Could not open directory [%s]. There was an "
                            "unspecified error." % (path))

    logging.debug("Directory resource ID is (%d)." % (sd))
    return sd

def _sftp_closedir(sd):
    logging.debug("Closing directory: %d" % (sd))

    result = c_sftp_closedir(sd)
    if result != SSH_NO_ERROR:
        raise SftpError("Could not close directory.")

def _sftp_readdir(sftp_session_int, sd):
    attr = c_sftp_readdir(sftp_session_int, sd)

    if not attr:
        return None

    return EntryAttributes(attr)

def _sftp_attributes_free(attr):
    c_sftp_attributes_free(attr)

def _sftp_dir_eof(sd):
    return (c_sftp_dir_eof(sd) == 1)

def _sftp_open(sftp_session_int, filepath, access_type, mode):
    logging.debug("Opening file: %s" % (filepath))

    sf = c_sftp_open(sftp_session_int, filepath, access_type, mode)
    if sf is None:
        type_ = sftp_get_error(sftp_session_int)
        if type_ >= 0:
            raise SftpError("Could not open file [%s]: %s" % 
                            (filepath, sftp_get_error_string(type_)))
        else:
            raise SftpError("Could not open file [%s]. There was an "
                            "unspecified error." % (filepath))

    logging.debug("File [%s] opened as [%s]." % (filepath, sf))
    return sf

def _sftp_close(sf):
    logging.debug("Closing file: %s" % (sf))

    result = c_sftp_close(sf)
    if result != SSH_NO_ERROR:
        raise SftpError("Close failed with code (%d)." % (result))

def _sftp_write(sf, buffer_):
    buffer_raw = create_string_buffer(buffer_)
    result = c_sftp_write(sf, cast(buffer_raw, c_void_p), len(buffer_))
    if result < 0:
        raise SftpError("Could not write to file.")

def _sftp_tell(sf):
    position = c_sftp_tell(sf)
    if position < 0:
        raise SftpError("Could not read current position in file.")

    return position
    
def _sftp_seek(sf, position):
    if c_sftp_seek(sf, position) < 0:
        raise SftpError("Could not seek to the position (%d)." % (position))
    
def _sftp_read(sf, count):
    buffer_ = create_string_buffer(count)
    received_bytes = c_sftp_read(sf, cast(buffer_, c_void_p), c_size_t(count))
    if received_bytes < 0:
        raise SftpError("Read failed.")

    return buffer_.raw[0:received_bytes]

def _sftp_fstat(sf):
    attr = c_sftp_fstat(sf)
    if attr is None:
        raise SftpError("Could not acquire attributes for FSTAT.")

    return EntryAttributes(attr)

def _sftp_rewind(sf):
    # Returns VOID.
    c_sftp_rewind(sf)

def _sftp_stat(sftp_session_int, file_path):
    attr = c_sftp_stat(sftp_session_int, c_char_p(file_path))
    if attr is None:
        type_ = sftp_get_error(sftp_session_int)
        if type_ >= 0:
            raise SftpError("Could not acquire attributes for STAT of [%s]: "
                            "%s" % (file_path, sftp_get_error_string(type_)))
        else:
            raise SftpError("Could not acquire attributes for STAT of [%s]. "
                            "There was an unspecified error." % (file_path))

    return EntryAttributes(attr)

def _sftp_rename(sftp_session_int, filepath_old, filepath_new):
    result = c_sftp_rename(sftp_session_int, 
                           c_char_p(filepath_old), 
                           c_char_p(filepath_new))

    if result < 0:
        type_ = sftp_get_error(sftp_session_int)
        if type_ >= 0:
            raise SftpError("Rename of [%s] to [%s] failed: %s" % 
                            (filepath_old, 
                             filepath_new, 
                             sftp_get_error_string(type_)))
        else:
            raise SftpError("Rename of [%s] to [%s] failed. There was an "
                            "unspecified error." %
                            (filepath_old, filespace_new))

def _sftp_chmod(sftp_session_int, file_path, mode):
    result = c_sftp_chmod(sftp_session_int, c_char_p(file_path), c_int(mode))

    if result < 0:
        type_ = sftp_get_error(sftp_session_int)
        if type_ >= 0:
            raise SftpError("CHMOD of [%s] for mode [%o] failed: %s" %
                            (file_path, mode, sftp_get_error_string(type_)))
        else:
            raise SftpError("CHMOD of [%s] for mode [%o] failed. There was " %
                            "an unspecified error." % (file_path, mode))

def _sftp_chown(sftp_session_int, file_path, uid, gid):
    result = c_sftp_chown(sftp_session_int, 
                          c_char_p(file_path), 
                          c_int(uid), 
                          c_int(gid))

    if result < 0:
        type_ = sftp_get_error(sftp_session_int)
        if type_ >= 0:
            raise SftpError("CHOWN of [%s] for UID (%d) and GID (%d) failed: "
                            "%s" % 
                            (file_path, uid, gid, 
                             sftp_get_error_string(type_)))
        else:
            raise SftpError("CHOWN of [%s] for UID (%d) and GID (%d) failed. "
                            "There was an unspecified error." % 
                            (file_path, mode))

def _sftp_mkdir(sftp_session_int, path, mode):
    logging.debug("Creating directory: %s" % (path))

    result = c_sftp_mkdir(sftp_session_int, c_char_p(path), c_int(mode))

    if result < 0:
        type_ = sftp_get_error(sftp_session_int)
        if type_ >= 0:
            raise SftpError("MKDIR of [%s] for mode [%o] failed: %s" %
                            (path, mode, sftp_get_error_string(type_)))
        else:
            raise SftpError("MKDIR of [%s] for mode [%o] failed. There was " %
                            "an unspecified error." % (path, mode))

def _sftp_rmdir(sftp_session_int, path):
    logging.debug("Deleting directory: %s" % (path))

    result = c_sftp_rmdir(sftp_session_int, c_char_p(path))

    if result < 0:
        type_ = sftp_get_error(sftp_session_int)
        if type_ >= 0:
            raise SftpError("RMDIR of [%s] failed: %s" % 
                            (path, sftp_get_error_string(type_)))
        else:
            raise SftpError("RMDIR of [%s] failed. There was an unspecified "
                            "error." % (path))

def _sftp_lstat(sftp_session_int, file_path):
    attr = c_sftp_lstat(sftp_session_int, c_char_p(file_path))

    if attr is None:
        type_ = sftp_get_error(sftp_session_int)
        if type_ >= 0:
            raise SftpError("LSTAT of [%s] failed: %s" % 
                            (file_path, sftp_get_error_string(type_)))
        else:
            raise SftpError("LSTAT of [%s] failed. There was an unspecified "
                            "error." % (file_path))

    return EntryAttributes(attr)

def _sftp_unlink(sftp_session_int, file_path):
    logging.debug("Deleting file: %s" % (file_path))

    result = c_sftp_lstat(sftp_session_int, c_char_p(file_path))

    if result < 0:
        type_ = sftp_get_error(sftp_session_int)
        if type_ >= 0:
            raise SftpError("Unlink of [%s] failed: %s" % 
                            (file_path, sftp_get_error_string(type_)))
        else:
            raise SftpError("Unlink of [%s] failed. There was an unspecified "
                            "error." % (file_path))

def _sftp_readlink(sftp_session_int, file_path):
    target = c_sftp_readlink(sftp_session_int, c_char_p(file_path))

    if target is None:
        type_ = sftp_get_error(sftp_session_int)
        if type_ >= 0:
            raise SftpError("Read of link [%s] failed: %s" % 
                            (file_path, sftp_get_error_string(type_)))
        else:
            raise SftpError("Read of link [%s] failed. There was an "
                            "unspecified error." % (file_path))

    return target

def _sftp_symlink(sftp_session_int, to, from_):
    result = c_sftp_symlink(sftp_session_int, c_char_p(to), c_char_p(from_))

    if result < 0:
        type_ = sftp_get_error(sftp_session_int)
        if type_ >= 0:
            raise SftpError("Symlink of [%s] to target [%s] failed: %s" % 
                            (from_, to, sftp_get_error_string(type_)))
        else:
            raise SftpError("Symlink of [%s] to target [%s] failed. There was "
                            "an unspecified error." % (from_, to))

def _sftp_setstat(sftp_session_int, file_path, entry_attributes):
    result = c_sftp_setstat(sftp_session_int,
                            c_char_p(file_path),
                            entry_attributes.raw)

    if result < 0:
        type_ = sftp_get_error(sftp_session_int)
        if type_ >= 0:
            raise SftpError("Set-stat on [%s] failed: %s" % 
                            (file_path, sftp_get_error_string(type_)))
        else:
            raise SftpError("Set-stat on [%s] failed. There was an "
                            "unspecified error." % (file_path))

def _sftp_listdir(sftp_session_int, path):
    logging.debug("Listing directory: %s" % (path))

    with SftpDirectory(sftp_session_int, path) as sd_:
        while 1:
            attributes = _sftp_readdir(sftp_session_int, sd_)
            if attributes is None:
                break

            yield attributes

        if not _sftp_dir_eof(sd_):
            raise SftpError("We're done iterating the directory, but it's not "
                            "at EOF.")

def _sftp_utimes(sftp_session_int, file_path, atime_epoch, mtime_epoch):
    atime = CTimeval()
    mtime = CTimeval()

    atime.tv_sec = int(atime_epoch)
    atime.tv_usec = 0

    mtime.tv_sec = int(mtime_epoch)
    mtime.tv_usec = 0

    times = (CTimeval * 2)(atime, mtime)

    result = c_sftp_utimes(sftp_session_int, 
                           c_char_p(file_path), 
                           byref(times))

    if result < 0:
        raise SftpError("Times updated of [%s] failed." % (file_path))

def _sftp_utimes_dt(sftp_session_int, file_path, atime_dt, mtime_dt):
    _sftp_utimes(sftp_session_int, 
                 file_path, 
                 mktime(atime_dt.timetuple()), 
                 mktime(mtime_dt.timetuple()))


class SftpSession(object):
    def __init__(self, ssh_session):
        self.__ssh_session_int = getattr(ssh_session, 
                                         'session_id', 
                                         ssh_session)
        self.__log = logging.getLogger('SSH_SESSION(%s)' % 
                                       (self.__ssh_session_int))

    def __enter__(self):
        self.__sftp_session_int = _sftp_new(self.__ssh_session_int)
        _sftp_init(self.__sftp_session_int)

        return self

    def __exit__(self, e_type, e_value, e_tb):
        _sftp_free(self.__sftp_session_int)

    def stat(self, file_path):
        return _sftp_stat(self.__sftp_session_int, file_path)

    def rename(self, filepath_old, filepath_new):
        return _sftp_rename(self.__sftp_session_int, filepath_old, filepath_new)

    def chmod(self, file_path, mode):
        return _sftp_chmod(self.__sftp_session_int, file_path, mode)

    def chown(self, file_path, uid, gid):
        return _sftp_chown(self.__sftp_session_int, file_path, uid, gid)

    def mkdir(self, path, mode=0o755):
        return _sftp_mkdir(self.__sftp_session_int, path, mode)

    def rmdir(self, path):
        return _sftp_rmdir(self.__sftp_session_int, path)

    def lstat(self, file_path):
        return _sftp_lstat(self.__sftp_session_int, file_path)

    def unlink(self, file_path):
        return _sftp_unlink(self.__sftp_session_int, file_path)

    def readlink(self, file_path):
        return _sftp_readlink(self.__sftp_session_int, file_path)

    def symlink(self, to, from_):
        return _sftp_symlink(self.__sftp_session_int, to, from_)

    def setstat(self, file_path, entry_attributes):
        return _sftp_setstat(self.__sftp_session_int, file_path, entry_attributes)

    def listdir(self, path):
        return _sftp_listdir(self.__sftp_session_int, path)

    def recurse(self, path, dir_cb, listing_cb, max_listing_size=0, 
                max_depth=None):
        """Recursively iterate a directory. Invoke callbacks for directories 
        and entries (both are optional, but it doesn't make sense unless one is 
        provided). "max_listing_size" will allow for the file-listing to be 
        chunked into manageable pieces. "max_depth" limited how deep recursion 
        goes. This can be used to make it easy to simply read a single 
        directory in chunks.
        """
                
        q = deque([(path, 0)])
        while q:
            (path, current_depth) = q.popleft()

            entries = self.listdir(path)
            collected = []
            for entry in entries:
                file_path = ('%s/%s' % (path, entry.name))

                if entry.is_directory:
                    if entry.name == '.' or entry.name == '..':
                        continue

                    if dir_cb is not None:
                        dir_cb(path, file_path, entry)

                    new_depth = current_depth + 1
                    
                    if max_depth is not None and max_depth >= new_depth:
                        q.append((file_path, new_depth))
                elif entry.is_regular and listing_cb is not None:
                    collected.append((file_path, entry))
                    if max_listing_size > 0 and \
                       max_listing_size <= len(collected):
                        listing_cb(path, collected)
                        collected = []

            if listing_cb is not None and max_listing_size == 0 or len(collected) > 0:
                listing_cb(path, collected)

    def write_to_local(self, filepath_from, filepath_to, mtime_dt=None):
        """Open a remote file and write it locally."""

        self.__log.debug("Writing [%s] -> [%s]." % (filepath_from, 
                                                    filepath_to))

        with SftpFile(sftp, filepath_from, 'r') as sf_from:
            with SftpFile(sftp, filepath_to, 'w') as sf_to:
                while 1:
                    part = sf_from.read(MAX_MIRROR_WRITE_CHUNK_SIZE)
                    sf_to.write(part)

                    if len(part) < MAX_MIRROR_WRITE_CHUNK_SIZE:
                        break

        if mtime_dt is None:
            mtime_dt = datetime.now()

        mtime_epoch = mktime(mtime_dt.timetuple())
        utime(filepath_to, (mtime_epoch, mtime_epoch))
    
    def mirror(self, path_from, path_to):
        """Recursively mirror the contents of "path_from" into "path_to"."""
    
        q = deque([''])
        while q:
            path = q.popleft()
            
            full_from = ('%s/%s' % (path_from, path)) if path else path_from
            full_to = ('%s/%s' % (path_to, path)) if path else path_to

            subdirs = self.__mirror_inner(full_from, full_to)
            for subdir in subdirs:
                q.append(('%s/%s' % (path, subdir)) if path else subdir)

    def __mirror_inner(self, path_from, path_to):
        """Mirror a single directory. Return a list of subdirectory names (do
        not include full path).
        """

        # Make sure the destination exists.

        try:
            mkdir(path_to)
        except OSError:
            pass

        local_dirs = set()
        def local_dir_cb(parent_path, full_path, filename):
            local_dirs.add(filename)
        
        local_entites = set()
        local_files = set()
        def local_listing_cb(parent_path, listing):
            for file_path in listing:
                entity = (entry.name, int(entry.modified_time), entry.size)
                local_entities.add(entity)
                local_files.add(entry.name)

        local_recurse(path_to, 
                      local_dir_cb, 
                      local_listing_cb, 
                      MAX_MIRROR_LISTING_CHUNK_SIZE, 
                      0)

        remote_dirs = set()
        def remote_dir_cb(parent_path, full_path, entry):
            remote_dirs.add(entry.name)

        remote_entities = set()
        remote_files = set()
        remote_dictionary = {}
        def remote_listing_cb(parent_path, listing):
            for (file_path, entry) in listing:
                entity = (entry.name, entry.modified_time, entry.size)
                remote_entities.add(entity)
                remote_files.add(entry.name)
                remote_dictionary[entry.name] = entry

        sftp.recurse(path_from, 
                     remote_dir_cb, 
                     remote_listing_cb, 
                     MAX_MIRROR_LISTING_CHUNK_SIZE,
                     0)

        # Now, calculate the differences.

        new_dirs = remote_dirs - local_dirs
        deleted_dirs = local_dirs - remote_dirs

        # Get the files from remote that aren't identical to existing local 
        # entries. These will be copied.
        missing_entities = remote_entities - local_entities

        # Get the files from local that aren't identical to existing remote
        # entries. These will be deleted.
        deleted_entities = local_entities - remote_entities

        # Delete all remote-deleted directories.
        for name in deleted_dirs:
            rmtree('%s/%s' % (path_to, name))

        # Delete all remote-deleted non-directory entries, regardless of type.
        for (name, mtime, size) in deleted_entities:
            unlink('%s/%s' % (path_to, name))

        # Create new directories.
        for name in new_dirs:
            mkdir('%s/%s' % (path_to, name))

        # Write new/changed files. Handle all but "unknown" file types.
        for (name, mtime, size) in missing_entities:
            entry = remote_dictionary[name]
            filepath_from = ('%s/%s' % (path_from, name))
            filepath_to = ('%s/%s' % (path_to, name))

            if entry.is_regular:
                self.write_to_local(filepath_from, 
                                    filepath_to, 
                                    entry.modified_time_dt)

            elif entry.is_symlink:
                linked_to = self.readlink(filepath_to)
            
                # filepath_to: The physical file.
                # linked_to: The target.
                self.symlink(linked_to, filepath_to)

            elif entry.is_special:
                # SSH can't indulge us for devices, etc..
                self.__log.warn("Skipping 'special' file: %s" % 
                                (filepath_from))

        return list(remote_dirs)

    def utimes(self, file_path, atime_epoch, mtime_epoch):
        _sftp_utimes(self.__sftp_session_int, 
                     file_path, 
                     atime_epoch, 
                     mtime_epoch)

    def utimes_dt(self, file_path, atime_dt, mtime_dt):
        _sftp_utimes_dt(self.__sftp_session_int, file_path, atime_dt, mtime_dt)
        
    @property
    def session_id(self):
        return self.__sftp_session_int


class SftpDirectory(object):
    def __init__(self, sftp_session, path):
        self.__sftp_session_int = getattr(sftp_session, 
                                          'session_id', 
                                          sftp_session)
        self.__path = path

    def __enter__(self):
        self.__sd = _sftp_opendir(self.__sftp_session_int, self.__path)
        return self.__sd

    def __exit__(self, e_type, e_value, e_tb):
        _sftp_closedir(self.__sd)


class SftpFile(object):
    def __init__(self, sftp_session, filepath, access_type_om='r', 
                 create_mode=DEFAULT_CREATE_MODE):

        at_im = self.__at_om_to_im(access_type_om)

        self.__sftp_session_int = getattr(sftp_session, 
                                          'session_id', 
                                          sftp_session)

        self.__filepath = filepath
        self.__access_type = at_im
        self.__create_mode = create_mode

    def __repr__(self):
        return ('<SFTP_FILE [%s] \"%s\">' % 
                (self.__access_type[0], self.__filepath))

    def __at_om_to_im(self, om):
        """Convert an "outer" access mode to an "inner" access mode.
        Returns a tuple of:

            (<system access mode>, <is append>, <is universal newlines>).
        """

        original_om = om
        
        if om[0] == 'U':
            om = om[1:]
            is_um = True
        else:
            is_um = False

        if om == 'r':
            return (original_om, O_RDONLY, False, is_um)
        elif om == 'w':
            return (original_om, O_WRONLY | O_CREAT | O_TRUNC, False, is_um)
        elif om == 'a':
            return (original_om, O_WRONLY | O_CREAT, False, is_um)
        elif om == 'r+':
            return (original_om, O_RDWR | O_CREAT, False, is_um)
        elif om == 'w+':
            return (original_om, O_RDWR | O_CREAT | O_TRUNC, False, is_um)
        elif om == 'a+':
            return (original_om, O_RDWR | O_CREAT, True, is_um)
        else:
            raise Exception("Outer access mode [%s] is invalid." % 
                            (original_om))

    def __enter__(self):
        """This is the only way to open a file resource."""

        self.__sf = _sftp_open(self.__sftp_session_int, 
                               self.__filepath, 
                               self.access_type_int, 
                               self.__create_mode)

        if self.access_type_is_append is True:
            self.seek(self.filesize)

        return SftpFileObject(self)

    def __exit__(self, e_type, e_value, e_tb):
        _sftp_close(self.__sf)

    def write(self, buffer_):
        return _sftp_write(self.__sf, buffer_)

    def seek(self, position):
        return _sftp_seek(self.__sf, position)

    def read(self, size):
        """Read a length of bytes. Return empty on EOF."""

        return _sftp_read(self.__sf, size)

    def fstat(self):
        return _sftp_fstat(self.__sf)
        
    def rewind(self):
        return _sftp_rewind(self.__sf)

    @property
    def sf(self):
        return self.__sf

    @property
    def position(self):
        return _sftp_tell(self.__sf)

    @property
    def filesize(self):
        return self.fstat().size

    @property
    def filepath(self):
        return self.__filepath

    @property
    def access_type_str(self):
        return self.__access_type[0]

    @property
    def access_type_int(self):
        return self.__access_type[1]

    @property
    def access_type_is_append(self):
        return self.__access_type[2]
    
    @property
    def access_type_has_universal_nl(self):
        return self.__access_type[3]


class EntryAttributes(object):
    """This wraps the raw attribute type, and frees it at destruction."""

    def __init__(self, attr_raw):
        self.__attr_raw = attr_raw

    def __del__(self):
        _sftp_attributes_free(self.__attr_raw)

    def __getattr__(self, key):
        return getattr(self.__attr_raw.contents, key)

    def __repr__(self):
        return repr(self.__attr_raw.contents)

    def __str__(self):
        return str(self.__attr_raw.contents)

    @property
    def raw(self):
        return self.__attr_raw


class StreamBuffer(object):
    def __init__(self):
        self.__stream = StringIO()

    def read_until_nl(self, read_cb):
        captured = StringIO()

        i = 0
        found = False
        nl = None
        done = False

        while found is False and done is False:
            position = self.__stream.tell()
            couplet = self.__stream.read(2)

            if len(couplet) < 2:
                logging.debug("Couplet is a dwarf of (%d) bytes." % 
                              (len(couplet)))

                more_data = read_cb()
                logging.debug("Retrieved (%d) more bytes." % (len(more_data)))
                
                if more_data != '':
                    self.__stream.write(more_data)
                    self.__stream.seek(position)

                    # Re-read.
                    couplet = self.__stream.read(2)
                    logging.debug("Couplet is now (%d) bytes." % 
                                  (len(couplet)))
                elif couplet == '':
                    done = True
                    continue

            if len(couplet) == 2:
                # We represent a \r\n newline.
                if couplet == '\r\n':
                    nl = couplet
                    found = True

                    captured.write(couplet)
                
                # We represent a one-byte newline that's in the first position.
                elif couplet[0] == '\r' or couplet[0] == '\n':
                    nl = couplet[0]
                    found = True

                    captured.write(couplet[0])
                    self.__stream.seek(-1, SEEK_CUR)
                    
                # The first position is an ordinary character. If there's a
                # newline in the second position, we'll pick it up on the next
                # round.
                else:
                    captured.write(couplet[0])
                    self.__stream.seek(-1, SEEK_CUR)
            elif len(couplet) == 1:
                # This is the last [odd] byte of the file.

                if couplet[0] == '\r' or couplet[0] == '\n':
                    nl = couplet[0]
                    found = True

                captured.write(couplet[0])
                
                done = True

            i += 1

        data = captured.getvalue()
        return (data, nl)


class SftpFileObject(object):
    """A file-like object interface for SFTP resources."""

    __block_size = 8192

    def __init__(self, sf):
        self.__sf = sf
        self.__buffer = StreamBuffer()
        self.__offset = 0
        self.__buffer_offset = 0
        self.__newlines = {}
        self.__eof = False
        self.__log = logging.getLogger('FILE(%s)' % (sf))

    def __repr__(self):
        return ('<SFTP_FILE_OBJ [%s] \"%s\">' % 
                (self.mode, self.name.replace('"', '\\"')))

    def write(self, buffer_):
        self.__log.debug("Writing (%d) bytes." % (len(buffer_)))
        self.__sf.write(buffer_)

    def read(self, size=None):
        """Read a length of bytes. Return empty on EOF. If 'size' is omitted, 
        return whole file.
        """

        if size is not None:
            return self.__sf.read(size)

        block_size = self.__class__.__block_size

        buffers = []
        received_bytes = 0
        while 1:
            partial = self.__sf.read(block_size)
            self.__log.debug("Reading (%d) bytes. (%d) bytes returned." % 
                             (block_size, len(partial)))

            buffers.append(partial)
            received_bytes += len(partial)

            if len(partial) < block_size:
                self.__log.debug("End of file.")
                break

        self.__log.debug("Read (%d) bytes for total-file." % (received_bytes))

        return ''.join(buffers)

    def close(self):
        """Close the resource."""

        self.__sf.close()

    def seek(self, offset, whence=SEEK_SET):
        """Reposition the file pointer."""

        if whence == SEEK_SET:
            self.__sf.seek(offset)
        elif whence == SEEK_CUR:
            self.__sf.seek(self.tell() + offset)
        elif whence == SEEK_END:
            self.__sf.seek(self.__sf.filesize - offset)

    def tell(self):
        """Report the current position."""

        return self.__sf.position

    def flush(self):
        """Flush data. This is a no-op in our context."""

        pass

    def isatty(self):
        """Only return True if connected to a TTY device."""

        return False

    def __iter__(self):
        return self

    def next(self):
        """Iterate through lines of text."""

        next_line = self.readline()
        if next_line == '':
            self.__log.debug("No more lines (EOF).")
            raise StopIteration()

        return next_line

    def readline(self, size=None):
        """Read a single line of text with EOF."""

# TODO: Add support for Unicode.
        (line, nl) = self.__buffer.read_until_nl(self.__retrieve_data)

        if self.__sf.access_type_has_universal_nl and nl is not None:
            self.__newlines[nl] = True

        return line
        
    def __retrieve_data(self):
        """Read more data from the file."""

        if self.__eof is True:
            return ''

        logging.debug("Reading another block.")        
        block = self.read(self.__block_size)
        if block == '':
            self.__log.debug("We've encountered the EOF.")
            self.__eof = True

        return block

    def readlines(self, sizehint=None):
        self.__log.debug("Reading all lines.")

        collected = []
        total = 0
        for line in iter(self):
            collected.append(line)
            total += len(line)

            if sizehint is not None and total > sizehint:
                break

        self.__log.debug("Read whole file as (%d) lines." % (len(collected)))
        return ''.join(collected)

    @property
    def closed(self):
        raise False
    
    @property
    def encoding(self):
        return None
        
    @property
    def mode(self):
        return self.__sf.access_type_str
        
    @property
    def name(self):
        return self.__sf.filepath

    @property
    def newlines(self):
        if self.__sf.access_type_has_universal_nl is False:
            raise AttributeError("Universal newlines are unavailable since "
                                 "not requested.")

        return tuple(self.__newlines.keys())

    @property
    def raw(self):
        return self.__sf

# c_sftp_seek64
# c_sftp_tell64

# c_sftp_extensions_get_count
# c_sftp_extensions_get_name
# c_sftp_fstatvfs
# c_sftp_server_version
# c_sftp_statvfs
# c_sftp_statvfs_free

