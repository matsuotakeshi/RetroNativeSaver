"""One supervisor-owned config snapshot, shared read-only with its workers."""
import hashlib
import json
import mmap
import uuid

ENV_KEY = 'RNS_WORKER_CONFIG_SNAPSHOT'
MAX_BYTES = 32 * 1024 * 1024


class ConfigSnapshot:
    def __init__(self, config):
        payload = json.dumps(config, ensure_ascii=False).encode('utf-8')
        if not isinstance(config, dict) or not 0 < len(payload) <= MAX_BYTES:
            raise ValueError('Invalid or oversized config snapshot')
        tag = 'Local\\RNSConfig_' + uuid.uuid4().hex
        self.descriptor = json.dumps(dict(tag=tag, size=len(payload), sha256=hashlib.sha256(payload).hexdigest()))
        self.mapping = mmap.mmap(-1, len(payload), tagname=tag)
        try:
            self.mapping.write(payload)
        except BaseException:
            self.mapping.close()
            raise

    def apply(self, environment):
        environment[ENV_KEY] = self.descriptor

    def close(self):
        if self.mapping is not None:
            self.mapping.close()
            self.mapping = None


def load_worker_config(path, environment):
    from launch_options import load_config
    descriptor = environment.get(ENV_KEY)
    if descriptor is None:
        return load_config(path)  # Explicit standalone --worker remains supported.
    try:
        meta = json.loads(descriptor)
        tag, size, digest = meta['tag'], meta['size'], meta['sha256']
        if (not isinstance(tag, str) or not tag.startswith('Local\\RNSConfig_')
                or type(size) is not int or not 0 < size <= MAX_BYTES
                or not isinstance(digest, str) or len(digest) != 64):
            raise ValueError('Invalid snapshot descriptor')
        with mmap.mmap(-1, size, tagname=tag, access=mmap.ACCESS_READ) as shared:
            payload = shared.read(size)
        if hashlib.sha256(payload).hexdigest() != digest:
            raise ValueError('Config snapshot integrity mismatch')
        config = json.loads(payload)
        if not isinstance(config, dict):
            raise ValueError('Config snapshot must be an object')
        print(f'[config] using supervisor snapshot sha256={digest}', flush=True)
        return config
    except Exception as exc:
        # Never fall back to a potentially changed file when a snapshot was promised.
        raise ValueError(f'Cannot read supervisor config snapshot: {exc}') from exc
