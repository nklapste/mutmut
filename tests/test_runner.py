#!/usr/bin/python
# -*- coding: utf-8 -*-

"""pytests for :mod:`muckup.runner`"""

from datetime import datetime

import pytest

from muckup.runner import popen_streaming_output, TimeoutError, \
    MutationTestRunner


def test_timeout():
    start = datetime.now()

    with pytest.raises(TimeoutError):
        popen_streaming_output('python -c "import time; time.sleep(4)"',
                               lambda line: line, timeout=0.1)

    assert (datetime.now() - start).total_seconds() < 3


def test_timeout_non_timeout():
    start = datetime.now()

    popen_streaming_output('python -c "import time; time.sleep(4)"',
                           lambda line: line, timeout=20)

    assert (datetime.now() - start).total_seconds() >= 4
    assert (datetime.now() - start).total_seconds() < 10


def test_compute_return_code():
    assert 8 == MutationTestRunner.compute_return_code(0, 0, 1)
    assert 9 == MutationTestRunner.compute_return_code(0, 0, 1, Exception)

    assert 4 == MutationTestRunner.compute_return_code(0, 1, 0)
    assert 5 == MutationTestRunner.compute_return_code(0, 1, 0, Exception)

    assert 12 == MutationTestRunner.compute_return_code(0, 1, 1)
    assert 13 == MutationTestRunner.compute_return_code(0, 1, 1, Exception)

    assert 2 == MutationTestRunner.compute_return_code(1, 0, 0)
    assert 3 == MutationTestRunner.compute_return_code(1, 0, 0, Exception)

    assert 10 == MutationTestRunner.compute_return_code(1, 0, 1)
    assert 11 == MutationTestRunner.compute_return_code(1, 0, 1, Exception)

    assert 6 == MutationTestRunner.compute_return_code(1, 1, 0)
    assert 7 == MutationTestRunner.compute_return_code(1, 1, 0, Exception)

    assert 14 == MutationTestRunner.compute_return_code(1, 1, 1)
    assert 15 == MutationTestRunner.compute_return_code(1, 1, 1, Exception)
