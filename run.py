import sys
import os

from icyripper.ripper import StreamRipper
from icyripper.logger import setup_logging

current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)

if __name__ == '__main__':
    setup_logging()
    ripper = StreamRipper('http://prem2.di.fm:80/chillntropicalhouse?insert_token_here', '/home/rikkt0r/songs')
    ripper.rip()
    # ripper.debug_stream(1024 * 64)
