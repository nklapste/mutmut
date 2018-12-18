#!/usr/bin/python
# -*- coding: utf-8 -*-

"""main entrypoint for mutmut"""

from __future__ import print_function

import argparse
import os
import sys
from shutil import copy

from glob2 import glob

from mutmut.mutators import gen_mutations_for_file
from mutmut.runner import MutationTestRunner

if sys.version_info < (3, 0):  # pragma: no cover (python 2 specific)
    # noinspection PyCompatibility,PyUnresolvedReferences
    from ConfigParser import ConfigParser, NoOptionError, NoSectionError  # pylint: disable=import-error
else:
    # noinspection PyUnresolvedReferences,PyCompatibility
    from configparser import ConfigParser, NoOptionError, NoSectionError


def get_python_source_files(path_to_mutate, test_dirs):
    """Yield the paths to all python source files

    :param path_to_mutate: path of the source package/file to mutate
    :type path_to_mutate: str

    :param test_dirs: list of the directories containing testing files. These
        directories and their contained files will be filtered from the output
        as we don't want to mutate tests.
    :type test_dirs: list[str]

    :return: list of paths to python source files
    :rtype: list[str]
    """
    source_files = []
    if os.path.isdir(path_to_mutate):
        for root, dirs, files in os.walk(path_to_mutate):
            dirs[:] = [d for d in dirs if
                       os.path.join(root, d) not in test_dirs]
            for filename in files:
                if filename.endswith('.py'):
                    source_files.append(os.path.join(root, filename))
    else:
        source_files.append(path_to_mutate)
    return source_files


def get_python_test_files(paths_to_mutate, test_dirs):
    """Yield the paths to all python source files

    :param paths_to_mutate: path of the source package/file(s) to mutate
    :type paths_to_mutate: list[str]

    :param test_dirs: list of the directories containing testing files.
        These directories and their contained files will be attempted to be
        discovered
    :type test_dirs: list[str]

    :return: list of paths to python source testing files
    :rtype: list[str]
    """
    test_files = []
    # search for the tests within the cwd
    for p in test_dirs:
        test_files.extend(glob(p, recursive=True))

    # search for tests within the source directories
    for p in paths_to_mutate:
        for pt in test_dirs:
            test_files.extend(glob(p + '/**/' + pt, recursive=True))
    return test_files


def get_argparser():
    """Get the main argument parser for mutmut

    :return: the main argument parser for mutmut
    :rtype: argparse.ArgumentParser
    """
    parser = argparse.ArgumentParser(
        prog="mutmut",
        description="Simple mutation testing for python.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )

    parser.add_argument("file_or_dir", nargs="+",
                        help="Path to the source package(s)/file(s) to "
                             "mutate test.")
    parser.add_argument("-t", "--tests", dest="test_dirs", default="tests",
                        nargs="*",
                        help="Path to the testing package(s)/file(s) to "
                             "challenge mutations with. These files will be "
                             "excluded from being mutated.")
    parser.add_argument("-r", "--runner", default='python -m pytest -x',
                        help="Python test runner (and its arguments) to "
                             "invoke each mutation test run.")
    parser.add_argument("-q", "--quiet-stdout", action="store_true",
                        dest="output_capture",
                        help="Turn off output capture of spawned "
                             "sub-processes.")
    parser.add_argument("-co", "--use-coverage", dest="use_coverage",
                        help="Only mutate code that is covered within the "
                             "`.coverage` file.")

    return parser


def main(argv=sys.argv[1:]):
    """main entrypoint for mutmut

    :rtype: int
    """
    # stop python from creating .pyc files
    os.environ['PYTHONDONTWRITEBYTECODE'] = '1'

    parser = get_argparser()
    args = parser.parse_args(argv)

    using_testmon = '--testmon' in args.runner
    mutation_test_runner = MutationTestRunner(
        test_command=args.runner,
        using_testmon=using_testmon,
    )

    # run the unmutated tests
    # Note: if testmon was specified in the runner this should create
    # the `.testmondata` file
    # Note: if coverage was specified in the runner this should create
    # the `.coverage` file
    mutation_test_runner.time_test_suite()

    # save a copy of the testmon data for later usage in mutation tests
    if using_testmon:
        copy('.testmondata', '.testmondata-initial')

    # configure coverage filtering for mutant generation
    if args.use_coverage:
        if not os.path.exists(".coverage"):
            raise FileNotFoundError(
                'No valid `.coverage` file found. Are you sure your test '
                'runner is generating one?'
            )
        print("Using `.coverage` data to filter mutation creation")

        import coverage
        coverage_data = coverage.CoverageData()
        coverage_data.read_file(".coverage")

        covered_lines_by_filename = {}
        def _exclude(context):
            try:
                covered_lines = covered_lines_by_filename[context.filename]
            except KeyError:
                covered_lines = coverage_data.lines(os.path.abspath(context.filename))
                covered_lines_by_filename[context.filename] = covered_lines

            if covered_lines is None:
                return True
            current_line = context.current_line_index + 1
            if current_line not in covered_lines:
                return True
            return False
    else:
        def _exclude(context):
            return False

    # generate mutants
    mutants = []
    paths_to_mutate = args.file_or_dir
    test_dirs = get_python_test_files(paths_to_mutate, args.test_dirs)
    for path in paths_to_mutate:
        for filename in get_python_source_files(path, test_dirs):
            for mutant in gen_mutations_for_file(filename, _exclude):
                mutants.append(mutant)

    print("generated {} mutants".format(len(mutants)))

    mutation_test_runner.run_mutation_tests(mutants)

    return 0


if __name__ == '__main__':
    sys.exit(main())  # pylint: disable=no-value-for-parameter

