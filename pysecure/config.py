DEFAULT_CREATE_MODE = 0o644
DEFAULT_EXECUTE_READ_BLOCK_SIZE = 8192
NONBLOCK_READ_TIMEOUT_MS = 1500
DEFAULT_SHELL_READ_BLOCK_SIZE = 1024
MAX_MIRROR_LISTING_CHUNK_SIZE = 5
MAX_MIRROR_WRITE_CHUNK_SIZE = 8192

try:
    from pysecure import development
except ImportError:
    IS_DEVELOPMENT = False
else:
    IS_DEVELOPMENT = True

