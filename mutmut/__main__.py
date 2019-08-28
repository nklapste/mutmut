#!/usr/bin/env python
# -*- coding: utf-8 -*-

import argparse
import fnmatch
import itertools
import os
import shlex
import subprocess
import sys
import traceback
from io import open
from os.path import isdir, exists
from shutil import move, copy
from threading import Timer
from time import time

import click
from glob2 import glob

from mutmut import __version__ as mutmut_version
from mutmut import mutate_file, Context, list_mutations, __version__, \
    BAD_TIMEOUT, OK_SUSPICIOUS, BAD_SURVIVED, OK_KILLED, UNTESTED
from mutmut.cache import register_mutants, update_mutant_status, \
    print_result_cache, cached_mutation_status, hash_of_tests, \
    filename_and_mutation_id_from_pk, cached_test_time, set_cached_test_time, \
    update_line_numbers, print_result_cache_junitxml, get_unified_diff

spinner = itertools.cycle('⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏')


def status_printer():
    """Manage the printing and in-place updating of a line of characters

    .. note::
        If the string is longer than a line, then in-place updating may not
        work (it will print a new line at each refresh).
    """
    last_len = [0]

    def p(s):
        s = next(spinner) + ' ' + s
        len_s = len(s)
        output = '\r' + s + (' ' * max(last_len[0] - len_s, 0))
        sys.stdout.write(output)
        sys.stdout.flush()
        last_len[0] = len_s

    return p


print_status = status_printer()


def guess_paths_to_mutate():
    """Guess the path to source code to mutate

    :rtype: str
    """
    this_dir = os.getcwd().split(os.sep)[-1]
    if isdir('lib'):
        return 'lib'
    elif isdir('src'):
        return 'src'
    elif isdir(this_dir):
        return this_dir
    elif isdir(this_dir.replace('-', '_')):
        return this_dir.replace('-', '_')
    elif isdir(this_dir.replace(' ', '_')):
        return this_dir.replace(' ', '_')
    elif isdir(this_dir.replace('-', '')):
        return this_dir.replace('-', '')
    elif isdir(this_dir.replace(' ', '')):
        return this_dir.replace(' ', '')
    raise FileNotFoundError(
        'Could not figure out where the code to mutate is. '
        'Please specify it on the command line using --paths-to-mutate, '
        'or by adding "paths_to_mutate=code_dir" in setup.cfg to the [mutmut] section.')


def do_apply(mutation_pk, dict_synonyms, backup):
    """Apply a specified mutant to the source code

    :param mutation_pk: mutmut cache primary key of the mutant to apply
    :type mutation_pk: str

    :param dict_synonyms: list of synonym keywords for a python dictionary
    :type dict_synonyms: list[str]

    :param backup: if :obj:`True` create a backup of the source file
        before applying the mutation
    :type backup: bool
    """
    filename, mutation_id = filename_and_mutation_id_from_pk(int(mutation_pk))

    update_line_numbers(filename)

    context = Context(
        mutation_id=mutation_id,
        filename=filename,
        dict_synonyms=dict_synonyms,
    )
    mutate_file(
        backup=backup,
        context=context,
    )


null_out = open(os.devnull, 'w')


class Config(object):
    def __init__(self, swallow_output, test_command, exclude_callback,
                 baseline_time_elapsed, test_time_multiplier, test_time_base,
                 backup, dict_synonyms, total, using_testmon, cache_only,
                 tests_dirs, hash_of_tests, pre_mutation, post_mutation):
        self.swallow_output = swallow_output
        self.test_command = test_command
        self.exclude_callback = exclude_callback
        self.baseline_time_elapsed = baseline_time_elapsed
        self.test_time_multipler = test_time_multiplier
        self.test_time_base = test_time_base
        self.backup = backup
        self.dict_synonyms = dict_synonyms
        self.total = total
        self.using_testmon = using_testmon
        self.progress = 0
        self.skipped = 0
        self.cache_only = cache_only
        self.tests_dirs = tests_dirs
        self.hash_of_tests = hash_of_tests
        self.killed_mutants = 0
        self.surviving_mutants = 0
        self.surviving_mutants_timeout = 0
        self.suspicious_mutants = 0
        self.post_mutation = post_mutation
        self.pre_mutation = pre_mutation

    def print_progress(self):
        print_status('{}/{}  🎉 {}  ⏰ {}  🤔 {}  🙁 {}'.format(self.progress,
                                                               self.total,
                                                               self.killed_mutants,
                                                               self.surviving_mutants_timeout,
                                                               self.suspicious_mutants,
                                                               self.surviving_mutants))


DEFAULT_TESTS_DIR = 'tests/:test/'


def get_argparser():
    parser = argparse.ArgumentParser(
        description="Python mutation testing made easy.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    parser.add_argument(
        "--version",
        action="version",
        help="display mutmut lib version.",
        version='%(prog)s {}'.format(mutmut_version)
    )
    parser.add_argument(
        "--no-backup",
        dest="no_backup",
        action="store_true",
        help="WARNING DANGEROUS: disable creating backups of source files "
             "before applying mutants."
    )
    parser.add_argument(
        "--dict-synonyms",
        dest="dict_synonyms",
        nargs="*",
        default=[]
    )

    subparsers = parser.add_subparsers(
        dest='command',
        help='mutmut command to invoke.'
    )

    run_parser = subparsers.add_parser(
        "run",
        help='generate and test mutants.'
    )
    run_parser.add_argument(
        "--paths-to-mutate",
        dest="paths_to_mutate",
        help="paths to search for python source code to mutate."
    )
    run_parser.add_argument(
        "--paths-to-exclude",
        dest="paths_to_exclude",
        help="paths to exclude searching for python source code to mutate."
    )
    run_parser.add_argument(
        "--tests-dir",
        dest="tests_dir"
    )
    run_parser.add_argument(
        "--mutant-id",
        help="if specified only this mutant will be tested."
    )
    run_parser.add_argument(
        "--runner",
        default="python -m pytest -x",
        help="test runner command to invoke and test mutants with."
    )
    run_parser.add_argument(
        "-m",
        "--test-time-multiplier",
        dest="test_time_multiplier",
        type=float,
        default=2.0,
        help="multiple of the initial test run time that must pass before "
             "timing out a mutation test run"
    )
    run_parser.add_argument(
        "-b",
        "--test-time-base",
        dest="test_time_base",
        type=float,
        default=0.0,
        help="additional base time that must pass before timing out a "
             "mutation test run."
    )
    run_parser.add_argument(
        "--pre-mutation",
        dest="pre_mutation",
        help="command to execute before a mutation "
             "has been applied and tested."
    )
    run_parser.add_argument(
        "--post-mutation",
        dest="post_mutation",
        help="command to execute after a mutation "
             "has been tested and reverted."
    )
    # TODO: wack
    run_parser.add_argument(
        "-s",
        "--swallow-output",
        dest="swallow_output",
        action="store_true",
        help="print test runner output during mutation tests."
    )
    run_parser_mutant_exclusion_me_group = run_parser.add_argument_group(
        "Mutant Exclusion").add_mutually_exclusive_group()
    run_parser_mutant_exclusion_me_group.add_argument(
        "--use-coverage",
        dest="use_coverage",
        action="store_true",
        help='only mutate lines hit in the .coverage report.'
    )
    run_parser_mutant_exclusion_me_group.add_argument(
        "--use-patch-file",
        dest="use_patch_file",
        help='only mutate lines added/changed in the given patch file.'
    )
    # TODO: doc
    run_parser.add_argument(
        "--cache-only",
        dest="cache_only",
        action="store_true",
    )

    results_parser = subparsers.add_parser(
        "results",
        help='print cached mutmut results.'
    )

    apply_parser = subparsers.add_parser(
        "apply",
        help='apply a mutation on disk.'
    )
    apply_parser.add_argument(
        "mutant_id",
        help="id of the mutant to apply."
    )

    show_parser = subparsers.add_parser(
        "show",
        help="show a mutant"
    )
    show_parser.add_argument(
        "--show-diffs"
    )
    show_parser.add_argument(
        "--show-only-file",
        dest="show_only_file"
    )
    show_parser_group = show_parser.add_argument_group().add_mutually_exclusive_group()
    show_parser_group.add_argument(
        "--mutant-id",
        help="if specified only this mutant will be shown."
    )
    show_parser_group.add_argument(
        "--all"
    )

    junitxml_parser = subparsers.add_parser(
        "junitxml",
        help='show mutation diffs as a junitxml report.'
    )
    policy_choices = ['ignore', 'skipped', 'error', 'failure']
    junitxml_parser.add_argument(
        "--suspicious-policy",
        dest="suspicious_policy",
        choices=policy_choices,
        default="ignore"
    )
    junitxml_parser.add_argument(
        '--untested-policy',
        dest="untested_policy",
        choices=policy_choices,
        default="ignore"
    )

    return parser


def junitxml_main(dict_synonyms, suspicious_policy, untested_policy):
    print_result_cache_junitxml(dict_synonyms, suspicious_policy,
                                untested_policy)
    return 0


def results_main():
    print_result_cache()
    return 0


def apply_main(mutant_id, dict_synonyms, backup):
    do_apply(mutant_id, dict_synonyms, backup)
    return 0


def show_main(dict_synonyms, show_only_file, mutant_id=None):
    if not mutant_id:
        print_result_cache(show_diffs=True, dict_synonyms=dict_synonyms,
                           print_only_filename=show_only_file)
        return 0
    print(get_unified_diff(mutant_id, dict_synonyms))
    return 0


def run_main(paths_to_mutate, backup, runner, tests_dir,
             test_time_multiplier, test_time_base,
             swallow_output, use_coverage, dict_synonyms, cache_only,
             pre_mutation, post_mutation,
             use_patch_file, paths_to_exclude, mutant_id=None):
    if paths_to_mutate is None:
        paths_to_mutate = guess_paths_to_mutate()

    if not isinstance(paths_to_mutate, (list, tuple)):
        paths_to_mutate = [x.strip() for x in paths_to_mutate.split(',')]

    if not paths_to_mutate:
        raise ValueError(
            "No paths to mutate were found. You must manually specify the "
            "list of paths to mutate. Either as a command line argument using"
            " the '--paths-to-mutate' argument, or by setting paths_to_mutate "
            "under the section [mutmut] in setup.cfg"
        )

    tests_dirs = []
    for p in tests_dir.split(':'):
        tests_dirs.extend(glob(p, recursive=True))

    for p in paths_to_mutate:
        for pt in tests_dir.split(':'):
            tests_dirs.extend(glob(p + '/**/' + pt, recursive=True))
    del tests_dir

    # stop python from creating .pyc files
    os.environ['PYTHONDONTWRITEBYTECODE'] = '1'

    print("""
    - Mutation testing starting -

    These are the steps:
    1. A full test suite run will be made to make sure we
       can run the tests successfully and we know how long
       it takes (to detect infinite loops for example)
    2. Mutants will be generated and checked

    Results are stored in .mutmut-cache.
    Print found mutants with `mutmut results`.

    Legend for output:
    🎉 Killed mutants.   The goal is for everything to end up in this bucket.
    ⏰ Timeout.          Test suite took 10 times as long as the baseline so were killed.
    🤔 Suspicious.       Tests took a long time, but not long enough to be fatal.
    🙁 Survived.         This means your tests needs to be expanded.
    """)
    using_testmon = '--testmon' in runner
    baseline_time_elapsed = time_test_suite(
        swallow_output=not swallow_output,
        test_command=runner,
        using_testmon=using_testmon
    )

    if using_testmon:
        copy('.testmondata', '.testmondata-initial')

    if use_coverage and not exists('.coverage'):
        raise FileNotFoundError(
            'No .coverage file found. You must generate a coverage file to use this feature.')

    # if we're running in a mode with externally whitelisted lines
    if use_coverage or use_patch_file:
        covered_lines_by_filename = {}
        if use_coverage:
            coverage_data = read_coverage_data()
        else:
            assert use_patch_file
            covered_lines_by_filename = read_patch_data(use_patch_file)
            coverage_data = None

        def _exclude(context):
            try:
                covered_lines = covered_lines_by_filename[context.filename]
            except KeyError:
                if coverage_data is not None:
                    covered_lines = coverage_data.lines(
                        os.path.abspath(context.filename))
                    covered_lines_by_filename[context.filename] = covered_lines
                else:
                    covered_lines = None

            if covered_lines is None:
                return True
            current_line = context.current_line_index + 1
            if current_line not in covered_lines:
                return True
            return False
    else:
        def _exclude(context):
            del context
            return False

    paths_to_exclude = [path.strip() for path in paths_to_exclude.split(',')]
    if mutant_id:
        mutations_by_file = get_mutations_by_file_from_cache(mutant_id)
    else:
        mutations_by_file = gen_mutations_by_file(
            paths_to_mutate=paths_to_mutate,
            tests_dirs=tests_dirs,
            paths_to_exclude=paths_to_exclude,
            dict_synonyms=dict_synonyms,
            exclude_check=_exclude,
        )

    total = sum(len(mutations) for mutations in mutations_by_file.values())

    print('2. Checking mutants')
    config = Config(
        swallow_output=not swallow_output,
        test_command=runner,
        exclude_callback=_exclude,
        baseline_time_elapsed=baseline_time_elapsed,
        backup=backup,
        dict_synonyms=dict_synonyms,
        total=total,
        using_testmon=using_testmon,
        cache_only=cache_only,
        tests_dirs=tests_dirs,
        hash_of_tests=hash_of_tests(tests_dirs),
        test_time_multiplier=test_time_multiplier,
        test_time_base=test_time_base,
        pre_mutation=pre_mutation,
        post_mutation=post_mutation,
    )

    try:
        run_mutation_tests(config=config, mutations_by_file=mutations_by_file)
    except Exception as e:
        traceback.print_exc()
        return compute_exit_code(config, e)
    else:
        return compute_exit_code(config)
    finally:
        print()  # make sure we end the output with a newline


def main(argv=sys.argv[1:]):
    """return exit code, after performing an mutation test run.

    :return: the exit code from executing the mutation tests
    :rtype: int
    """
    parser = get_argparser()
    args = parser.parse_args(argv)

    backup = not args.no_backup
    dict_synonyms = [x.strip() for x in args.dict_synonyms]
    # TODO: replace command
    if args.command == 'show':
        return show_main(dict_synonyms, args.show_only_file, args.mutant_id)

    if args.command == 'results':
        return results_main()

    if args.command == 'junitxml':
        return junitxml_main(dict_synonyms, args.suspicious_policy, args.untested_policy)

    if args.command == 'apply':
        return apply_main(args.mutant_id, dict_synonyms, backup)
    if args.command == 'run':
        return run_main(
            args.paths_to_mutate,
            backup,
            args.runner,
            args.tests_dir,
            args.test_time_multiplier,
            args.test_time_base,
            args.swallow_output,
            args.use_coverage,
            dict_synonyms,
            args.cache_only,
            args.pre_mutation,
            args.post_mutation,
            args.use_patch_file,
            args.paths_to_exclude,
            mutant_id=args.mutant_id
        )


def get_mutations_by_file_from_cache(mutation_pk):
    filename, mutation_id = filename_and_mutation_id_from_pk(int(mutation_pk))
    return {filename: [mutation_id]}


def gen_mutations_by_file(paths_to_mutate, tests_dirs, paths_to_exclude,
                          dict_synonyms, exclude_check=lambda x: False):
    mutations_by_file = {}
    for path in paths_to_mutate:
        for filename in python_source_files(path, tests_dirs,
                                            paths_to_exclude):
            update_line_numbers(filename)
            with open(filename) as f:
                source = f.read()
            context = Context(
                source=source,
                filename=filename,
                exclude=exclude_check,
                dict_synonyms=dict_synonyms,
            )

            try:
                mutations_by_file[filename] = list_mutations(context)
                register_mutants(mutations_by_file)
            except Exception as e:
                raise RuntimeError(
                    'Failed while creating mutations for file {} on line "{}"'.format(
                        context.filename, context.current_source_line)) from e
    return mutations_by_file


def popen_streaming_output(cmd, callback, timeout=None):
    """Open a subprocess and stream its output without hard-blocking.

    :param cmd: the command to execute within the subprocess
    :type cmd: str

    :param callback: function that intakes the subprocess' stdout line by line.
        It is called for each line received from the subprocess' stdout stream.
    :type callback: Callable[[Context], bool]

    :param timeout: the timeout time of the subprocess
    :type timeout: float

    :raises TimeoutError: if the subprocess' execution time exceeds
        the timeout time

    :return: the return code of the executed subprocess
    :rtype: int
    """
    if os.name == 'nt':  # pragma: no cover
        process = subprocess.Popen(
            shlex.split(cmd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        stdout = process.stdout
    else:
        master, slave = os.openpty()
        process = subprocess.Popen(
            shlex.split(cmd, posix=True),
            stdout=slave,
            stderr=slave
        )
        stdout = os.fdopen(master)
        os.close(slave)

    def kill(process_):
        """Kill the specified process on Timer completion"""
        try:
            process_.kill()
        except OSError:
            pass

    # python 2-3 agnostic process timer
    timer = Timer(timeout, kill, [process])
    timer.setDaemon(True)
    timer.start()

    while process.returncode is None:
        try:
            if os.name == 'nt':  # pragma: no cover
                line = stdout.readline()
                # windows gives readline() raw stdout as a b''
                # need to decode it
                line = line.decode("utf-8")
                if line:  # ignore empty strings and None
                    callback(line.rstrip())
            else:
                while True:
                    line = stdout.readline()
                    if not line:
                        break
                    callback(line.rstrip())
        except (IOError, OSError):
            # This seems to happen on some platforms, including TravisCI.
            # It seems like it's ok to just let this pass here, you just
            # won't get as nice feedback.
            pass
        if not timer.is_alive():
            raise TimeoutError(
                "subprocess running command '{}' timed out after {} seconds".format(
                    cmd, timeout))
        process.poll()

    # we have returned from the subprocess cancel the timer if it is running
    timer.cancel()

    return process.returncode


def tests_pass(config):
    """
    :type config: Config
    :return: :obj:`True` if the tests pass, otherwise :obj:`False`
    :rtype: bool
    """
    if config.using_testmon:
        copy('.testmondata-initial', '.testmondata')

    def feedback(line):
        if not config.swallow_output:
            print(line)
        config.print_progress()

    returncode = popen_streaming_output(config.test_command, feedback,
                                        timeout=config.baseline_time_elapsed * 10)
    return returncode == 0 or (config.using_testmon and returncode == 5)


def run_mutation(config, filename, mutation_id):
    """
    :type config: Config
    :type filename: str
    :type mutation_id: MutationID
    :return: (computed or cached) status of the tested mutant
    :rtype: str
    """
    context = Context(
        mutation_id=mutation_id,
        filename=filename,
        exclude=config.exclude_callback,
        dict_synonyms=config.dict_synonyms,
        config=config,
    )

    cached_status = cached_mutation_status(filename, mutation_id,
                                           config.hash_of_tests)
    if cached_status == BAD_SURVIVED:
        config.surviving_mutants += 1
    elif cached_status == BAD_TIMEOUT:
        config.surviving_mutants_timeout += 1
    elif cached_status == OK_KILLED:
        config.killed_mutants += 1
    elif cached_status == OK_SUSPICIOUS:
        config.suspicious_mutants += 1
    else:
        assert cached_status == UNTESTED, cached_status

    if cached_status != UNTESTED:
        return cached_status

    if config.pre_mutation:
        result = subprocess.check_output(config.pre_mutation,
                                         shell=True).decode().strip()
        if result:
            print(result)

    try:
        mutate_file(
            backup=True,
            context=context
        )
        start = time()
        try:
            survived = tests_pass(config)
        except TimeoutError:
            context.config.surviving_mutants_timeout += 1
            return BAD_TIMEOUT

        time_elapsed = time() - start
        if not survived and time_elapsed > config.test_time_base + (
                config.baseline_time_elapsed * config.test_time_multipler):
            config.suspicious_mutants += 1
            return OK_SUSPICIOUS

        if survived:
            context.config.surviving_mutants += 1
            return BAD_SURVIVED
        else:
            context.config.killed_mutants += 1
            return OK_KILLED
    finally:
        move(filename + '.bak', filename)

        if config.post_mutation:
            result = subprocess.check_output(config.post_mutation,
                                             shell=True).decode().strip()
            if result:
                print(result)


def run_mutation_tests(config, mutations_by_file):
    """
    :type config: Config
    :type mutations_by_file: dict[str, list[tuple]]
    """
    config.print_progress()
    for file, mutations in mutations_by_file.items():
        for mutation_id in mutations:
            status = run_mutation(config, file, mutation_id)
            update_mutant_status(file, mutation_id, status,
                                 config.hash_of_tests)
            config.progress += 1
            config.print_progress()


def read_coverage_data():
    """
    :rtype: CoverageData or None
    """
    try:
        # noinspection PyPackageRequirements,PyUnresolvedReferences
        from coverage import Coverage
    except ImportError as e:
        raise ImportError(
            'The --use-coverage feature requires the coverage library. Run "pip install coverage"') from e
    cov = Coverage('.coverage')
    cov.load()
    return cov.get_data()


def read_patch_data(patch_file_path):
    try:
        # noinspection PyPackageRequirements
        import whatthepatch
    except ImportError as e:
        raise ImportError(
            'The --use-patch feature requires the whatthepatch library. Run "pip install whatthepatch"') from e
    with open(patch_file_path) as f:
        diffs = whatthepatch.parse_patch(f.read())

    return {
        diff.header.new_path: {line_number for
                               old_line_number, line_number, text, *_ in
                               diff.changes if old_line_number is None}
        for diff in diffs
    }


def time_test_suite(swallow_output, test_command, using_testmon):
    """Execute a test suite specified by ``test_command`` and record
    the time it took to execute the test suite as a floating point number

    :param swallow_output: if :obj:`True` test stdout will be not be printed
    :type swallow_output: bool

    :param test_command: command to spawn the testing subprocess
    :type test_command: str

    :param using_testmon: if :obj:`True` the test return code evaluation will
        accommodate for ``pytest-testmon``
    :type using_testmon: bool

    :return: execution time of the test suite
    :rtype: float
    """
    cached_time = cached_test_time()
    if cached_time is not None:
        print(
            '1. Using cached time for baseline tests, to run baseline again delete the cache file')
        return cached_time

    print('1. Running tests without mutations')
    start_time = time()

    output = []

    def feedback(line):
        if not swallow_output:
            print(line)
        print_status('Running...')
        output.append(line)

    returncode = popen_streaming_output(test_command, feedback)

    if returncode == 0 or (using_testmon and returncode == 5):
        baseline_time_elapsed = time() - start_time
    else:
        raise RuntimeError(
            "Tests don't run cleanly without mutations. Test command was: {}\n\nOutput:\n\n{}".format(
                test_command, '\n'.join(output)))

    print('Done')

    set_cached_test_time(baseline_time_elapsed)

    return baseline_time_elapsed


def python_source_files(path, tests_dirs, paths_to_exclude=None):
    """Attempt to guess where the python source files to mutate are and yield
    their paths

    :param path: path to a python source file or package directory
    :type path: str

    :param tests_dirs: list of directory paths containing test files
        (we do not want to mutate these!)
    :type tests_dirs: list[str]

    :param paths_to_exclude: list of UNIX filename patterns to exclude
    :type paths_to_exclude: list[str]

    :return: generator listing the paths to the python source files to mutate
    :rtype: Generator[str, None, None]
    """
    paths_to_exclude = paths_to_exclude or []
    if isdir(path):
        for root, dirs, files in os.walk(path, topdown=True):
            for exclude_pattern in paths_to_exclude:
                dirs[:] = [d for d in dirs if
                           not fnmatch.fnmatch(d, exclude_pattern)]
                files[:] = [f for f in files if
                            not fnmatch.fnmatch(f, exclude_pattern)]

            dirs[:] = [d for d in dirs if
                       os.path.join(root, d) not in tests_dirs]
            for filename in files:
                if filename.endswith('.py'):
                    yield os.path.join(root, filename)
    else:
        yield path


def compute_exit_code(config, exception=None):
    """Compute an exit code for mutmut mutation testing

    The following exit codes are available for mutmut:
     * 0 if all mutants were killed (OK_KILLED)
     * 1 if a fatal error occurred
     * 2 if one or more mutants survived (BAD_SURVIVED)
     * 4 if one or more mutants timed out (BAD_TIMEOUT)
     * 8 if one or more mutants caused tests to take twice as long (OK_SUSPICIOUS)

     Exit codes 1 to 8 will be bit-ORed so that it is possible to know what
     different mutant statuses occurred during mutation testing.

    :param exception:
    :type exception: Exception
    :param config:
    :type config: Config

    :return: integer noting the exit code of the mutation tests.
    :rtype: int
    """
    code = 0
    if exception is not None:
        code = code | 1
    if config.surviving_mutants > 0:
        code = code | 2
    if config.surviving_mutants_timeout > 0:
        code = code | 4
    if config.suspicious_mutants > 0:
        code = code | 8
    return code


if __name__ == '__main__':
    sys.exit(main())
