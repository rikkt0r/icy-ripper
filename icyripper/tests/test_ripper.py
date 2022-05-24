import os
import random
import socket
from unittest import TestCase, mock
from unittest.mock import call

from icyripper.ripper import StreamRipper

current_dir = os.path.dirname(os.path.abspath(__file__))
tmp_dir = os.path.join(current_dir, '../..', 'tmp')


class EndOfStreamException(Exception):
    pass


class MockSocket:
    def __init__(self, *args, **kwargs):
        self.content = self._build_content()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False

    def _pass(self, *args, **kwargs):
        pass

    connect = _pass
    settimeout = _pass
    sendall = _pass

    def recv(self, size):
        if not len(self.content):
            raise EndOfStreamException('EOF!')
        _size = random.randint(size // 4, size // 2)
        data = self.content[:_size]
        self.content = self.content[_size:]
        return data

    def _build_content(self):
        title1 = b'StreamTitle=\'Some song - Some artist\';Whatever=aaaaaaaa'
        title2 = b'StreamTitle=\'Another - one\';'

        data = b'a' * random.randint(50, 99)
        data += str(len(data)).zfill(2).encode('utf8')
        data += b'HTTP/1.0 200 OK\r\nAccept-Ranges: bytes\r\nContent-Type: audio/aac\r\n' \
                b'icy-br:128\r\nicy-genre:Chill & Tropical House\r\n' \
                b'icy-name:Chill & Tropical House - DI.FM Premium\r\n' \
                b'icy-pub:0\r\nicy-url:https://www.di.fm\r\n' \
                b'Server: Icecast 2.4.0-kh3\r\n' \
                b'Cache-Control: no-cache, no-store\r\nPragma: no-cache\r\n' \
                b'Access-Control-Allow-Origin: *\r\n' \
                b'Access-Control-Allow-Headers: Origin, Accept, X-Requested-With, Content-Type\r\n' \
                b'Access-Control-Allow-Methods: GET, OPTIONS, HEAD\r\nConnection: Close\r\n' \
                b'Expires: Mon, 26 Jul 1997 05:00:00 GMT\r\nicy-metaint:16000\r\n\r\n'
        data += os.urandom(16000)
        data += b'\x07'
        data += title1
        data += b'\0' * (7 * 16 - len(title1))
        data += os.urandom(16000)
        data += b'\x05'
        data += title2
        data += b'\0' * (5 * 16 - len(title2))

        return data


class TestRipper(TestCase):
    def setUp(self):
        try:
            os.mkdir(tmp_dir)
        except FileExistsError:
            pass

        self.ripper = StreamRipper('http://prem2.di.fm:80/chillntropicalhouse?insert_token_here', tmp_dir)

    def test_debug(self):
        with mock.patch.object(socket, 'socket', mock.Mock(return_value=MockSocket())):
            with self.assertRaises(EndOfStreamException):
                self.ripper.rip()

    def test_connection_retry(self):
        with mock.patch.object(socket, 'socket', mock.Mock(return_value=MockSocket())):
            with mock.patch.object(StreamRipper, '_get_headers', side_effect=[TimeoutError, EndOfStreamException]):
                with mock.patch('icyripper.ripper.sleep', mock.Mock()) as sleep_mock:
                    with self.assertRaises(EndOfStreamException):
                        self.ripper.rip()

                self.assertEqual(sleep_mock.call_count, 1)
                self.assertEqual(sleep_mock.call_args, call(10.0, ))
