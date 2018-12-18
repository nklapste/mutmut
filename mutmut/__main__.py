#!/usr/bin/python
# -*- coding: utf-8 -*-

"""main entrypoint for mutmut"""

from __future__ import print_function

import argparse
import os
import sys
from shutil import copy

from glob2 import glob

from mutmut.file_collection import python_source_files, read_coverage_data
from mutmut.mutators import gen_mutations_for_file
from mutmut.runner import MutationTestRunner

if sys.version_info < (3, 0):  # pragma: no cover (python 2 specific)
    # noinspection PyCompatibility,PyUnresolvedReferences
    from ConfigParser import ConfigParser, NoOptionError, NoSectionError  # pylint: disable=import-error
else:
    # noinspection PyUnresolvedReferences,PyCompatibility
    from configparser import ConfigParser, NoOptionError, NoSectionError


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
    parser.add_argument("-b", "--backup", action="store_true",
                        dest="backup",
                        help="Create a backup of source files before mutations")  # TODO: help values
    parser.add_argument("file_or_dir", nargs="+",
                        help="Path to the source package(s)/file(s) to "
                             "mutate test. If no path is specified it will"
                             "be guessed.")
    parser.add_argument("-t", "--tests", dest="tests_dir", default="tests",
                        nargs="*",
                        help="Path to the testing file(s) to challenge "
                             "mutations with.")
    parser.add_argument("-r", "--runner", default='python -m pytest -x',
                        help="Python test runner (and its arguments) to "
                             "invoke each mutation test run.")
    parser.add_argument("-q", "--quiet-stdout", action="store_true",
                        dest="output_capture",
                        help="Turn off output capture of spawned "
                             "sub-processes.")
    parser.add_argument("-co", "--use-coverage", dest="use_coverage",
                        help="Only mutate code that is covered within the "
                             "specified `.coverage` file.")

    return parser


def main(argv=sys.argv[1:]):
    """main entrypoint for mutmut"""

    parser = get_argparser()
    args = parser.parse_args(argv)

    paths_to_mutate = args.file_or_dir

    tests_dirs = []
    for p in args.tests_dir:
        tests_dirs.extend(glob(p, recursive=True))

    for p in paths_to_mutate:
        for pt in args.tests_dir:
            tests_dirs.extend(glob(p + '/**/' + pt, recursive=True))

    # stop python from creating .pyc files
    os.environ['PYTHONDONTWRITEBYTECODE'] = '1'

    using_testmon = '--testmon' in args.runner

    print("{:=^79}".format(" Starting Mutation Tests "))
    print("Using test runner: {}".format(args.runner))

    if using_testmon:
        copy('.testmondata', '.testmondata-initial')

    if not args.use_coverage:
        def _exclude(context):
            return False
    else:
        if not os.path.exists(args.use_coverage):
            raise FileNotFoundError(
                'No valid `.coverage` file found. You must generate a coverage '
                'file to use this feature.'
            )
        covered_lines_by_filename = {}
        coverage_data = read_coverage_data(args.use_coverage)

        def _exclude(context):
            try:
                covered_lines = covered_lines_by_filename[context.filename]
            except KeyError:
                covered_lines = coverage_data.lines(
                    os.path.abspath(context.filename))
                covered_lines_by_filename[context.filename] = covered_lines

            if covered_lines is None:
                return True
            current_line = context.current_line_index + 1
            if current_line not in covered_lines:
                return True
            return False

    mutants = []

    for path in paths_to_mutate:
        for filename in python_source_files(path, tests_dirs):
            for mutant in gen_mutations_for_file(filename, _exclude):
                mutants.append(mutant)

    print("generated {} mutants".format(len(mutants)))
    MutationTestRunner(
        mutants=mutants,
        test_command=args.runner,
        using_testmon=using_testmon,
    ).run_mutation_tests()

    return 0


if __name__ == '__main__':
    sys.exit(main())  # pylint: disable=no-value-for-parameter
