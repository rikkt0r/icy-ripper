class ByteFifo:
    # https://stackoverflow.com/a/57748513
    """ byte FIFO buffer """
    def __init__(self):
        self._buf = bytearray()

    def put(self, data):
        self._buf.extend(data)

    def get(self, size):
        data = self._buf[:size]
        # The fast delete syntax
        # self._buf[:size] = b''
        del self._buf[:size]
        return data

    def peek(self, size):
        return self._buf[:size]

    def getvalue(self):
        # peek with no copy
        return self._buf

    def __len__(self):
        return len(self._buf)


def benchmark_ByteFifo():
    import time
    bfifo = ByteFifo()
    bfifo.put(b'a' * 1000000)  # a very long array
    t0 = time.time()
    for k in range(1000000):
        d = bfifo.get(4)  # "pop" from head
        bfifo.put(d)  # "push" in tail
    print('t = ', time.time() - t0)  # t = 0.897 on my machine


if __name__ == '__main__':
    benchmark_ByteFifo()
