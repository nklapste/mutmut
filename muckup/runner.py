#!/usr/bin/python
# -*- coding: utf-8 -*-

"""Mutation testing execution runner"""

from __future__ import print_function

import shlex
import subprocess
import sys
import time
from shutil import move, copy
from threading import Timer

from muckup.mutators import Mutant, UNTESTED, OK_KILLED, OK_SUSPICIOUS, \
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

    def kill(process_):
        """Kill the specified process on Timer completion"""
        try:
            process_.kill()
        except OSError:
            pass  # ignore

    # python 2-3 agnostic process timer
    timer = Timer(timeout, kill, [process])
    timer.start()

    while process.returncode is None:
        try:
            # -1 to remove the newline at the end
            line = process.stdout.readline()[:-1]
            callback(line)
        except OSError:
            # This seems to happen on some platforms, including TravisCI.
            # It seems like it's ok to just let this pass here, you just
            # won't get as nice feedback.
            pass
        if not timer.is_alive():
            raise TimeoutError("subprocess timed out")

        process.poll()

    # we have returned from the subprocess cancel the timer if it is running
    timer.cancel()

    return process.returncode


class MutationTestRunner:
    """Test runner for :class:`muckup.mutators.Mutant`s"""

    def __init__(self, test_command, swallow_output=True,
                 using_testmon=False, baseline_test_time=None):
        """Construct a MutationTestRunner

        :param test_command:
        :type test_command: str

        :param swallow_output:
        :type swallow_output: bool

        :param using_testmon:
        :type using_testmon: bool

        :param baseline_test_time:
        :type baseline_test_time: float or None
        """
        self.test_command = test_command
        self.swallow_output = swallow_output
        self.using_testmon = using_testmon
        self.baseline_test_time = baseline_test_time

    def run_mutation_tests(self, mutants):
        print("{:=^79}".format(" Starting Mutation Tests "))
        print("Using test runner: {}".format(self.test_command))
        if self.baseline_test_time is None:
            self.time_test_suite()
        for mutant in mutants:
            original, mutation = mutant.mutation_original_pair
            print("{}['{}'->'{}'] ".format(mutant.source_file, original, mutation), end='')
            self.test_mutant(mutant)
            print(mutant.status)
        return self.compute_return_code(mutants)

    def test_mutant(self, mutant):
        """Test a given mutant and set its respective status on completion

        :param mutant: The mutant to test.
        :type mutant: Mutant
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

    def time_test_suite(self):
        """Compute the unmutated test suite's execution time

        :raise RuntimeError: If the unmutated tests fail.
            Mutation testing cannot be done on a failing test suite.
        """
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

    # TODO: hookup
    @staticmethod
    def compute_return_code(mutants, exception=None):
        """Compute an error code similar to how pylint does. (using bit OR)

        The following output status codes are available for muckup:
         * 0 if all mutants were killed (OK_KILLED)
         * 1 if a fatal error occurred
         * 2 if one or more mutants survived (BAD_SURVIVED)
         * 4 if one or more mutants timed out (BAD_TIMEOUT)
         * 8 if one or more mutants caused tests to take twice as long (OK_SUSPICIOUS)
         status codes 1 to 8 will be bit-ORed so you can know which different
         categories has been issued by analysing the mutmut output status code

        :param mutants: The list of tested mutants.
        :type mutants: list[Mutant]

        :param exception: If an exception was thrown during test execution
            it should be given here.
        :type exception: class[Exception]

        :return: a integer noting the return status of the mutation tests.
        :rtype: int
        """
        code = 0
        if exception is not None:
            code = code | 1
        if any(mutant.status == BAD_SURVIVED for mutant in mutants):
            code = code | 2
        if any(mutant.status == BAD_TIMEOUT for mutant in mutants):
            code = code | 4
        if any(mutant.status == OK_SUSPICIOUS for mutant in mutants):
            code = code | 8
        return code
