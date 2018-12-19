#!/usr/bin/python
# -*- coding: utf-8 -*-

"""pytests for :mod:`muckup.runner`"""

import time

import pytest

from muckup.runner import popen_streaming_output, TimeoutError


def test_timeout():
    start = time.time()

    with pytest.raises(TimeoutError):
        popen_streaming_output('python -c "import time; time.sleep(4)"',
                               lambda line: line, timeout=0.1)

    assert (time.time() - start) < 3


def test_timeout_non_timeout():
    start = time.time()

    popen_streaming_output('python -c "import time; time.sleep(4)"',
                           lambda line: line, timeout=20)

    assert (time.time() - start) >= 4
    assert (time.time() - start) < 10
