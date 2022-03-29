#!/usr/bin/env python3
import sys
from os.path import dirname, join, isfile

sys.path.append(dirname(dirname(__file__)))

from server import VERSION

sys.stdout.write(VERSION)
sys.stdout.flush()
