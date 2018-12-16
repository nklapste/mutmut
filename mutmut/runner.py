#!/usr/bin/python
# -*- coding: utf-8 -*-

"""Mutation testing execution runner"""

import shlex
import subprocess
import sys
import time
from shutil import move, copy
from threading import Timer

from mutmut.mutators import Mutant, UNTESTED, OK_KILLED, OK_SUSPICIOUS, \
    BAD_SURVIVED, BAD_TIMEOUT

if sys.version_info < (3, 0):   # pragma: no cover (python 2 specific)
    class TimeoutError(OSError):
        """Timeout expired.

        python2.7 does not have this exception class natively so we add it for
        simplicity.
        """
else:
    TimeoutError = TimeoutError


def popen_streaming_output(cmd, callback, timeout=None):
    """Open a subprocess and stream its output without hard-blocking.

    :param cmd: the command to execute within the subprocess
    :type cmd: str

    :param callback: function to execute with the subprocess stdout output
    :param timeout: the timeout time for the processes' ``communication``
        call to complete
    :type timeout: float

    :raises TimeoutError: if the subprocesses' ``communication`` call times out

    :return: the return code of the executed subprocess
    :rtype: int
    """
    process = subprocess.Popen(
        shlex.split(cmd),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True
    )

    def kill(process):
        """Kill the specified process on Timer completion"""
        try:
            process.kill()
        except OSError:
            pass  # ignore

    # python 2-3 agnostic process timer
    timer = Timer(timeout, kill, [process])
    timer.start()

    while process.returncode is None:
        try:
            output, errors = process.communicate()
            if output.endswith("\n"):
                # -1 to remove the newline at the end
                output = output[:-1]
            line = output
            callback(line)
        except OSError:
            # This seems to happen on some platforms, including TravisCI.
            # It seems like it's ok to just let this pass here, you just
            # won't get as nice feedback.
            pass
        if not timer.is_alive():
            raise TimeoutError("subprocess timed out")

    # we have returned from the subprocess cancel the timer if it is running
    timer.cancel()

    return process.returncode


class MutationTestRunner:

    def __init__(self, mutants, test_command, swallow_output=True,
                 using_testmon=False, baseline_test_time=None):
        self.mutants = mutants
        self.test_command = test_command
        self.swallow_output = swallow_output
        self.using_testmon = using_testmon
        self.baseline_test_time = baseline_test_time

    def run_mutation_tests(self):
        if self.baseline_test_time is None:
            self._time_test_suite()
        for mutant in self.mutants:
            original, mutation = mutant.mutation_original_pair
            print("{}['{}'->'{}'] ".format(mutant.source_file, original, mutation), end='')
            self.test_mutant(mutant)
            print(mutant.status)

    def test_mutant(self, mutant):
        """

        :param mutant:
        :type mutant: Mutant
        :return:
        """
        if mutant.status != UNTESTED:
            return
        try:
            mutant.apply()
            start = time.time()
            try:
                survived = self.run_test(timeout=self.baseline_test_time * 10)
            except TimeoutError:
                mutant.status = BAD_TIMEOUT
            else:
                if time.time() - start > self.baseline_test_time * 2:
                    mutant.status = OK_SUSPICIOUS
                elif survived:
                    mutant.status = BAD_SURVIVED
                else:
                    mutant.status = OK_KILLED
        finally:
            move(mutant.source_file + '.bak', mutant.source_file)

    def _time_test_suite(self):
        start_time = time.time()
        green_suite = self.run_test()
        if green_suite:
            self.baseline_test_time = time.time() - start_time
            print("Ran unmutated test suite in {} seconds".format(self.baseline_test_time))
        else:
            raise RuntimeError("Mutation tests require a green suite")

    def run_test(self, timeout=None):
        """Run the test command and obtain a boolean noting if the test suite
        has passed

        :return: boolean noting if the test suite has passed
        :rtype: bool
        """
        if self.using_testmon:
            copy('.testmondata-initial', '.testmondata')

        def feedback(line):
            if not self.swallow_output:
                print(line)

        returncode = popen_streaming_output(
            cmd=self.test_command,
            callback=feedback,
            timeout=timeout
        )
        return returncode == 0 or (self.using_testmon and returncode == 5)
