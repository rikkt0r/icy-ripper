import os
import socket
import sys
import typing
from dataclasses import dataclass
from functools import wraps
from io import BytesIO
from pprint import pprint
from time import sleep
from urllib.parse import urlparse

from icyripper.buffer import ByteFifo

init_message = b"""GET %(path)s HTTP/1.1
User-Agent: Develop/0.1.2 Something/1.4
Connection: TE, close
TE: trailers
Host: %(host)s
Icy-MetaData: 1

""".replace(b'\n', b'\r\n')

BUFFER_SIZE = 1024 * 16
CHUNK_SIZE = 1024 * 4


class ShouldNeverHappenException(BaseException):
    pass


@dataclass
class RipperContext:
    song_store: BytesIO
    song_bytes_to_read: int
    song_chunk_size: int
    content_type: str

    initial_song: bool = True
    song_title: str = None


def retry_on_connection_timeout(retry_timeout: float):
    def wrapper(fn):
        @wraps(fn)
        def inner(_self, *args, **kwargs):
            try:
                return fn(_self, *args, **kwargs)
            except TimeoutError as e:
                print(e, file=sys.stderr)
                print("Retrying in %f" % retry_timeout)
                sleep(retry_timeout)
                # Drop buffers and everything. Restart the whole thing
                inner(_self, *args, **kwargs)

        return inner

    return wrapper


class StreamRipper:

    def __init__(self, stream_url, storage_dir):
        self.stream_url = stream_url
        self.storage_dir = storage_dir

    @staticmethod
    def parse_url(url) -> typing.Tuple[str, int, str]:
        parsed = urlparse(url)

        if ':' in parsed.netloc:
            host, port = parsed.netloc.split(':')
            port = int(port)
        else:
            host = parsed.netloc
            port = 80

        path = '%s?%s ' % (parsed.path, parsed.query)

        return host, port, path

    def dump_stream(self, size: int) -> bytearray:
        buffer = ByteFifo()
        host, port, path = self.parse_url(self.stream_url)

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.connect((host, port))
            sock.settimeout(6.0)
            sock.sendall(init_message % {b'host': host.encode('utf8'), b'path': path.encode('utf8')})

            while len(buffer) < size:
                buffer.put(sock.recv(CHUNK_SIZE))

        return buffer.get(len(buffer))

    def debug_stream(self, size: int):
        dump = self.dump_stream(size)
        header_idx = dump.find(b'\r\n\r\n') + 4
        stream_idx = dump.find(b'StreamTitle') - 1
        meta_len = dump[stream_idx] * 16
        print("header_idx, stream_idx, stream_idx - header_idx, meta_len")
        print(header_idx, stream_idx, stream_idx - header_idx, meta_len)

    @retry_on_connection_timeout(retry_timeout=10.0)
    def rip(self):
        buffer = ByteFifo()
        host, port, path = self.parse_url(self.stream_url)

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.connect((host, port))
            sock.settimeout(5.0)

            headers = self._get_headers(sock, buffer, host, path)
            song_chunk_size = int(headers['icy-metaint'])

            context = RipperContext(
                song_store=BytesIO(),
                song_bytes_to_read=song_chunk_size,
                song_chunk_size=song_chunk_size,
                content_type=headers['content-type']
            )

            while True:
                if len(buffer) < BUFFER_SIZE:
                    buffer.put(sock.recv(CHUNK_SIZE))

                if len(buffer) < 512:  # Socket may provide any amount of data
                    # Always have it somewhat filled so there would be no need to reiterate for metadata
                    continue

                if context.song_bytes_to_read > 0:
                    self._fill_song_buffer(buffer, context)

                elif context.song_bytes_to_read == 0:
                    self._handle_metadata(buffer, context)

                else:
                    raise ShouldNeverHappenException('context.song_bytes_to_read < 0')

    def _get_headers(self, sock: socket.socket, buffer: ByteFifo, host: str, path: str) -> dict:
        sock.sendall(init_message % {b'host': host.encode('utf8'), b'path': path.encode('utf8')})

        # Headers are typically shorter. Better act safe. Remaining buffer is a partial chunk of song
        while len(buffer) < 1024:
            buffer.put(sock.recv(CHUNK_SIZE))

        tmp = buffer.getvalue()
        header_end_idx = tmp.find(b'\r\n\r\n') + 4
        header_data = buffer.get(header_end_idx)
        headers = {}
        for header in header_data.split(b'\r\n'):
            if b':' in header:
                k, *v = header.decode('utf8').split(':')
                k = k.lower()
                if k == 'content-type' or k == 'server' or k.startswith('icy'):
                    headers[k] = "".join(v).strip()

        pprint(headers)
        print('-' * 120)

        return headers

    def _fill_song_buffer(self, buffer: ByteFifo, context: RipperContext):
        chunk = buffer.get(context.song_bytes_to_read)
        context.song_store.write(chunk)
        context.song_bytes_to_read -= len(chunk)

    def _handle_metadata(self, buffer: ByteFifo, context: RipperContext):
        chunk = buffer.get(1)
        if not chunk:
            raise ShouldNeverHappenException('song_bytes_to_read == 0 ---> if not chunk')

        elif chunk != b'\0':
            current_title = self._get_metadata_title(chunk, buffer)
            print("NOW RIPPIN':", current_title)

            if context.song_title is None:
                context.song_title = current_title

            elif context.song_title != current_title:
                # Time to write song to file
                self._write_file(current_title, context)

        context.song_bytes_to_read = context.song_chunk_size

    def _get_metadata_title(self, initial_chunk: bytearray, buffer: ByteFifo) -> str:
        metadata_to_read = ord(initial_chunk) * 16

        if metadata_to_read > len(buffer):
            raise ShouldNeverHappenException('metadata_to_read > len(buffer) (%d > %d)' % (
                metadata_to_read, len(buffer)
            ))

        chunk = buffer.get(metadata_to_read)
        metadata_to_read -= len(chunk)

        meta = {}
        # Strip doesn't work on bytearray. Workaround with slice
        for meta_entry in chunk[:chunk.find(b'\0')].split(b';'):
            if b'=' not in meta_entry:
                continue
            k, v = meta_entry.decode('utf8').split('=')
            meta[k] = v.strip("'")

        return meta['StreamTitle']

    def _write_file(self, current_title: str, context: RipperContext):
        ext = context.content_type.split('audio/')[1]  # possible bug?
        file_name = '%s.%s' % (context.song_title, ext)
        if context.initial_song:
            context.initial_song = False
            # When we begin rippin' it's almost certain that we don't have a full song
            file_name = 'PARTIAL_%s' % file_name
        context.song_title = current_title

        with open(os.path.join(self.storage_dir, file_name), 'wb') as f:
            pos = context.song_store.tell() - context.song_chunk_size  # metadata lags. silence detection needed
            print("Song len: %d kB" % (pos // 1024))
            context.song_store.seek(0)
            f.write(context.song_store.read(pos))
            tmp = context.song_store.read()
            context.song_store = BytesIO()
            context.song_store.write(tmp)
