#!/usr/bin/python
# -*- coding: utf-8 -*-

"""main entrypoint for mutmut"""

from __future__ import print_function

import argparse
import os
import sys
from io import open
from shutil import copy

from glob2 import glob

from mutmut.cache import update_line_numbers, hash_of_tests
from mutmut.file_collection import python_source_files, read_coverage_data, \
    get_or_guess_paths_to_mutate
from mutmut.runner import run_mutation_tests, Config,  time_test_suite, \
    add_mutations_by_file

if sys.version_info < (3, 0):   # pragma: no cover (python 2 specific)
    # noinspection PyCompatibility,PyUnresolvedReferences
    from ConfigParser import ConfigParser, NoOptionError, NoSectionError  # pylint: disable=import-error
    # This little hack is needed to get the click tester working on python 2.7
    orig_print = print

    def print(x='', **kwargs):
        orig_print(x.encode('utf8'), **kwargs)
else:
    # noinspection PyUnresolvedReferences,PyCompatibility
    from configparser import ConfigParser, NoOptionError, NoSectionError

START_MESSAGE = """
- Mutation testing starting - 

These are the steps:
1. A full test suite run will be made to make sure we 
   can run the tests successfully and we know how long 
   it takes (to detect infinite loops for example)
2. Mutants will be generated and checked

Mutants are written to the cache in the .mutmut-cache 
directory. Print found mutants with `mutmut results`.

Legend for output:
🎉 Killed mutants. The goal is for everything to end up in this bucket. 
⏰ Timeout. Test suite took 10 times as long as the baseline so were killed.  
🤔 Suspicious. Tests took a long time, but not long enough to be fatal. 
🙁 Survived. This means your tests needs to be expanded. 
"""


null_out = open(os.devnull, 'w')

DEFAULT_TESTS_DIR = 'tests/:test/'


def get_argparser():
    """Get the main argument parser for mutmut

    :return: the main argument parser for mutmut
    :rtype: argparse.ArgumentParser
    """
    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument("file_or_dir", nargs="+",
                        help="path to the source package(s)/file(s) to "
                             "mutate test")
    parser.add_argument("--use-coverage", dest="use_coverage",
                        help="only mutate code that is covered by tests note "
                             "this requires a ``.coverage`` file path to be "
                             "given")
    parser.add_argument("--runner", default='python -m pytest -x',
                        help="The python test runner (and its arguments) to "
                             "invoke each mutation test run ")
    parser.add_argument("--dict-synonyms", required=False, nargs="+",
                        default="")  # TODO: help values

    parser.add_argument("--tests", dest="tests_dir", default="tests",
                        help="path to the testing files to challenge with"
                             "mutations")
    parser.add_argument("-q", "--quiet-stdout", action="store_true",
                        dest="output_capture",
                        help="turn off output capture of sub-processes")

    parser.add_argument("--backup", action="store_true",
                        dest="backup")  # TODO: help values

    parser.add_argument("--cache-only", action="store_true",
                        dest="cache_only")  # TODO: help values
    # TODO: add ability to select on mutant again
    return parser


def main(argv=sys.argv[1:]):
    """main entrypoint for mutmut"""

    parser = get_argparser()
    args = parser.parse_args(argv)

    dict_synonyms = [x.strip() for x in args.dict_synonyms.split(',')]

    if args.use_coverage and not os.path.exists('.coverage'):
        raise FileNotFoundError(
            'No .coverage file found. You must generate a coverage '
            'file to use this feature.'
        )

    # TODO: add back
    # if command == 'results':
    #     print_result_cache()
    #     return 0
    #
    # if command == 'apply':
    #     do_apply(argument, dict_synonyms, args.backup)
    #     return 0

    if args.file_or_dir is None:
        paths_to_mutate = get_or_guess_paths_to_mutate()
    else:
        paths_to_mutate = args.file_or_dir

    if not isinstance(paths_to_mutate, (list, tuple)):
        paths_to_mutate = [path.strip() for path in paths_to_mutate.split(',')]

    if not paths_to_mutate:
        raise FileNotFoundError(
            'You must specify a list of paths to mutate. '
            'Either as a command line argument, or by setting paths_to_mutate '
            'under the section [mutmut] in setup.cfg'
        )

    tests_dirs = []
    for p in args.tests_dir.split(':'):
        tests_dirs.extend(glob(p, recursive=True))

    for p in paths_to_mutate:
        for pt in args.tests_dir.split(':'):
            tests_dirs.extend(glob(p + '/**/' + pt, recursive=True))

    # stop python from creating .pyc files
    os.environ['PYTHONDONTWRITEBYTECODE'] = '1'

    using_testmon = '--testmon' in args.runner

    print(START_MESSAGE)

    baseline_time_elapsed = time_test_suite(
        swallow_output=not args.output_capture,
        test_command=args.runner,
        using_testmon=using_testmon
    )

    if using_testmon:
        copy('.testmondata', '.testmondata-initial')

    if not args.use_coverage:
        def _exclude(context):
            return False
    else:
        covered_lines_by_filename = {}
        coverage_data = read_coverage_data()

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

    mutations_by_file = {}
    # TODO: ADD BACK
    # if argument is None:
    for path in paths_to_mutate:
        for filename in python_source_files(path, tests_dirs):
            update_line_numbers(filename)
            add_mutations_by_file(mutations_by_file, filename, _exclude,
                                  dict_synonyms)
    # TODO: ADD BACK

    # else:
    #     filename, mutation_id = \
    #         get_filename_and_mutation_id_from_pk(int(argument))
    #     mutations_by_file[filename] = [mutation_id]

    total = sum(len(mutations) for mutations in mutations_by_file.values())

    print('2. Checking mutants')
    run_mutation_tests(
        config=Config(
            swallow_output=not args.output_capture,
            test_command=args.runner,
            exclude_callback=_exclude,
            baseline_time_elapsed=baseline_time_elapsed,
            backup=args.backup,
            dict_synonyms=dict_synonyms,
            total=total,
            using_testmon=using_testmon,
            cache_only=args.cache_only,
            tests_dirs=tests_dirs,
            hash_of_tests=hash_of_tests(tests_dirs),
        ),
        mutations_by_file=mutations_by_file
    )
    return 0


if __name__ == '__main__':
    sys.exit(main())  # pylint: disable=no-value-for-parameter
