import os
import socket
from io import BytesIO
from pprint import pprint
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


def parse_url(url):
    parsed = urlparse(url)

    if ':' in parsed.netloc:
        host, port = parsed.netloc.split(':')
        port = int(port)
    else:
        host = parsed.netloc
        port = 80

    path = '%s?%s ' % (parsed.path, parsed.query)

    return host, port, path


def dump_stream(stream_url, size):
    buffer = ByteFifo()
    host, port, path = parse_url(stream_url)

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.connect((host, port))
        sock.settimeout(6.0)
        sock.sendall(init_message % {b'host': host.encode('utf8'), b'path': path.encode('utf8')})

        while len(buffer) < size:
            buffer.put(sock.recv(CHUNK_SIZE))

    return buffer.get(len(buffer))


def debug_stream(stream_url, size):
    dump = dump_stream(stream_url, size)
    header_idx = dump.find(b'\r\n\r\n') + 4
    stream_idx = dump.find(b'StreamTitle') - 1
    meta_len = dump[stream_idx] * 16
    print("header_idx, stream_idx, stream_idx - header_idx, meta_len")
    print(header_idx, stream_idx, stream_idx - header_idx, meta_len)


def run(stream_url, song_store_dir='/home/rikkt0r/songs'):
    # sock = socket.create_connection((host, port), timeout=5.0)

    buffer = ByteFifo()
    host, port, path = parse_url(stream_url)

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.connect((host, port))
        sock.settimeout(5.0)
        sock.sendall(init_message % {b'host': host.encode('utf8'), b'path': path.encode('utf8')})

        # Header and stuff
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
        song_chunk_size = int(headers['icy-metaint'])

        initial_song = True
        song_store = BytesIO()
        song_bytes_to_read = song_chunk_size
        song_title = None

        while True:
            if len(buffer) < BUFFER_SIZE:
                buffer.put(sock.recv(CHUNK_SIZE))

            if len(buffer) < 512:  # Socket may provide any amount of data
                # Always have it somewhat filled so there would be no need to reiterate for metadata
                continue

            if song_bytes_to_read < 0:
                raise ShouldNeverHappenException('song_bytes_to_read < 0')

            if song_bytes_to_read > 0:
                chunk = buffer.get(song_bytes_to_read)
                song_store.write(chunk)
                song_bytes_to_read -= len(chunk)

            elif song_bytes_to_read == 0:
                chunk = buffer.get(1)
                if not chunk:
                    raise ShouldNeverHappenException('song_bytes_to_read == 0 ---> if not chunk')

                elif chunk != b'\0':
                    metadata_to_read = ord(chunk) * 16

                    if metadata_to_read > len(buffer):
                        raise ShouldNeverHappenException('metadata_to_read > len(buffer) (%d > %d)' % (
                            metadata_to_read, len(buffer)
                        ))

                    chunk = buffer.get(metadata_to_read)
                    metadata_to_read -= len(chunk)

                    meta = {}
                    # Strip doesn't work on bytearray
                    for meta_entry in chunk[:chunk.find(b'\0')].split(b';'):
                        if b'=' not in meta_entry:
                            continue
                        k, v = meta_entry.decode('utf8').split('=')
                        meta[k] = v.strip("'")

                    current_title = meta['StreamTitle']
                    print("NOW RIPPIN':", current_title)
                    if song_title is None:
                        song_title = current_title
                    elif song_title != current_title:
                        # Time to write song to file
                        ext = headers['content-type'].split('audio/')[1]
                        file_name = '%s.%s' % (song_title, ext)
                        if initial_song:
                            initial_song = False
                            file_name = 'PARTIAL_%s' % file_name
                        song_title = current_title

                        with open(os.path.join(song_store_dir, file_name), 'wb') as f:
                            pos = song_store.tell()
                            print("Song len in bytes", pos)
                            song_store.seek(0)
                            f.write(song_store.read(pos-song_chunk_size))  # metadata lags
                            tmp = song_store.read()
                            song_store = BytesIO()
                            song_store.write(tmp)

                song_bytes_to_read = song_chunk_size
