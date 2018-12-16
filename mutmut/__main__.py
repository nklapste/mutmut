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

from mutmut.cache import update_line_numbers, hash_of_tests, \
    print_result_cache, get_filename_and_mutation_id_from_pk
from mutmut.file_collection import python_source_files, read_coverage_data, \
    get_or_guess_paths_to_mutate
from mutmut.runner import run_mutation_tests, Config, time_test_suite, \
    add_mutations_by_file, do_apply

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
    parser.add_argument("--dict-synonyms", required=False, nargs="*")  # TODO: help values
    parser.add_argument("-b", "--backup", action="store_true", dest="backup")  # TODO: help values
    subparsers = parser.add_subparsers(dest="command", help='commands')

    run_parser = subparsers.add_parser(
        'run',
        description="Run mutation testing.",
        help='Run mutation testing. '
             'Note: This should be executed before running either the '
             '`results` or `apply` commands.',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    run_parser.set_defaults(command="run")
    run_parser.add_argument("-m", "--mutant-id", dest="mutant_id",
                            default="all",
                            help='Id of the mutant to run, if not '
                                 'specified all mutants will be run.')
    run_parser.add_argument("-s", "--sources", nargs="*",
                            help="Path to the source package(s)/file(s) to "
                                 "mutate test. If no path is specified it will"
                                 "be guessed.")
    run_parser.add_argument("-t", "--tests", dest="tests_dir", default="tests",
                            help="Path to the testing file(s) to challenge "
                                 "mutations with.")
    run_parser.add_argument("-r", "--runner", default='python -m pytest -x',
                        help="Python test runner (and its arguments) to "
                             "invoke each mutation test run.")
    run_parser.add_argument("-q", "--quiet-stdout", action="store_true",
                            dest="output_capture",
                            help="Turn off output capture of spawned "
                                 "sub-processes.")
    run_parser.add_argument("-ca", "--cache-only", action="store_true",
                            dest="cache_only")  # TODO: help values
    run_parser.add_argument("-co", "--use-coverage", dest="use_coverage",
                            help="Only mutate code that is covered within the "
                                 "specified `.coverage` file.")

    results_parser = subparsers.add_parser(
        'results',
        help='Print the results of mutation testing.',
        description='Print the results of mutation testing.',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    results_parser.set_defaults(command="results")

    apply_parser = subparsers.add_parser(
        'apply',
        help='Apply a mutant onto the source code.',
        description='Apply a mutant onto the source code.',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    apply_parser.set_defaults(command="apply")
    apply_parser.add_argument('mutant_id', type=int,
                              help='Id of the mutant to apply to the source '
                                   'code.')

    return parser


def main(argv=sys.argv[1:]):
    """main entrypoint for mutmut"""

    parser = get_argparser()
    args = parser.parse_args(argv)

    if args.dict_synonyms is None:
        dict_synonyms = []
    else:
        dict_synonyms = args.dict_synonyms

    if args.command == 'results':
        print_result_cache()
        return 0

    if args.command == 'apply':
        if args.mutant_id == "all":
            raise ValueError("cannot apply all mutants,"
                             " please specifiy only one")  # TODO: better error
        do_apply(args.mutant_id, dict_synonyms, args.backup)
        return 0

    # else we have a run command
    if args.use_coverage and not os.path.exists(args.use_coverage):
        raise FileNotFoundError(
            'No .coverage file found. You must generate a coverage '
            'file to use this feature.'
        )

    if not args.sources:
        paths_to_mutate = get_or_guess_paths_to_mutate()
    else:
        paths_to_mutate = args.sources

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

    mutations_by_file = {}
    if args.mutant_id == "all":
        for path in paths_to_mutate:
            for filename in python_source_files(path, tests_dirs):
                update_line_numbers(filename)
                add_mutations_by_file(mutations_by_file, filename, _exclude,
                                      dict_synonyms)
    else:
        filename, mutation_id = \
            get_filename_and_mutation_id_from_pk(int(args.mutant_id))
        mutations_by_file[filename] = [mutation_id]

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
