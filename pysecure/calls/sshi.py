from ctypes import *

from pysecure.library import libssh
from pysecure.types import *

# Auxiliary calls.

c_strerror = libssh.strerror
c_free = libssh.free

# Function calls.

# LIBSSH_API ssh_session ssh_new(void);
c_ssh_new = libssh.ssh_new
c_ssh_new.argtypes = []
c_ssh_new.restype = c_ssh_session

# LIBSSH_API int ssh_options_set(ssh_session session, enum ssh_options_e type, const void *value);
c_ssh_options_set = libssh.ssh_options_set
c_ssh_options_set.argtypes = [c_ssh_session, c_int, c_void_p]
c_ssh_options_set.restype = c_int

# LIBSSH_API void ssh_free(ssh_session session);
c_ssh_free = libssh.ssh_free
c_ssh_free.argtypes = [c_ssh_session]
c_ssh_free.restype = None

# LIBSSH_API int ssh_connect(ssh_session session);
c_ssh_connect = libssh.ssh_connect
c_ssh_connect.argtypes = [c_ssh_session]
c_ssh_connect.restype = c_int

# LIBSSH_API void ssh_disconnect(ssh_session session);
c_ssh_disconnect = libssh.ssh_disconnect
c_ssh_disconnect.argtypes = [c_ssh_session]
c_ssh_disconnect.restype = None

# LIBSSH_API int ssh_is_server_known(ssh_session session);
c_ssh_is_server_known = libssh.ssh_is_server_known
c_ssh_is_server_known.argtypes = [c_ssh_session]
c_ssh_is_server_known.restype = c_int

# LIBSSH_API int ssh_get_pubkey_hash(ssh_session session, unsigned char **hash);
c_ssh_get_pubkey_hash = libssh.ssh_get_pubkey_hash
c_ssh_get_pubkey_hash.argtypes = [c_ssh_session, POINTER(POINTER(c_ubyte))]
c_ssh_get_pubkey_hash.restype = c_int

# LIBSSH_API char *ssh_get_hexa(const unsigned char *what, size_t len);
c_ssh_get_hexa = libssh.ssh_get_hexa
c_ssh_get_hexa.argtypes = [POINTER(c_ubyte), c_size_t]
c_ssh_get_hexa.restype = c_void_p

# LIBSSH_API void ssh_print_hexa(const char *descr, const unsigned char *what, size_t len);
c_ssh_print_hexa = libssh.ssh_print_hexa
c_ssh_print_hexa.argtypes = [c_char_p, POINTER(c_ubyte), c_size_t]
c_ssh_print_hexa.restype = None

# LIBSSH_API int ssh_write_knownhost(ssh_session session);
c_ssh_write_knownhost = libssh.ssh_write_knownhost
c_ssh_write_knownhost.argtypes = [c_ssh_session]
c_ssh_write_knownhost.restype = c_int

# LIBSSH_API int ssh_userauth_privatekey_file(ssh_session session, const char *username, const char *filename, const char *passphrase);
c_ssh_userauth_privatekey_file = libssh.ssh_userauth_privatekey_file
c_ssh_userauth_privatekey_file.argtypes = [c_ssh_session, c_char_p, c_char_p, c_char_p]
c_ssh_userauth_privatekey_file.restype = c_int

# LIBSSH_API const char *ssh_get_error(void *error);
c_ssh_get_error = libssh.ssh_get_error
c_ssh_get_error.argtypes = [c_void_p]
c_ssh_get_error.restype = c_char_p

# int ssh_init(void)
c_ssh_init = libssh.ssh_init
c_ssh_init.argtypes = []
c_ssh_init.restype = c_int

# int ssh_finalize(void)
c_ssh_finalize = libssh.ssh_finalize
c_ssh_finalize.argtypes = []
c_ssh_finalize.restype = c_int
