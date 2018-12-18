#!/usr/bin/python
# -*- coding: utf-8 -*-

"""Functionality for obtaining both source and test files for mutation
testing and generating a dictionary of valid mutants"""

import os
from os.path import isdir


def python_source_files(path, tests_dirs):
    """Yield the paths to all python source files

    :param path: path of the source file to mutate or path of the directory to
        yield source files from to mutate
    :type path: str

    :param tests_dirs: list of the directories containing testing files
    :type tests_dirs: list[str]

    :return: Generator yielding paths to python source files
    """
    if isdir(path):
        for root, dirs, files in os.walk(path):
            dirs[:] = [d for d in dirs if
                       os.path.join(root, d) not in tests_dirs]
            for filename in files:
                if filename.endswith('.py'):
                    yield os.path.join(root, filename)
    else:
        yield path


def read_coverage_data(path):
    """Read a coverage report a ``.coverage`` and return its coverage data.

    :param path: Path to a ``.coverage`` file
    :type path: str`

    :return: CoverageData from the given coverage file path
    :rtype: CoverageData
    """
    # noinspection PyPackageRequirements,PyUnresolvedReferences
    import coverage
    coverage_data = coverage.CoverageData()
    coverage_data.read_file(path)
    return coverage_data
