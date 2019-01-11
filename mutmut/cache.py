# -*- coding: utf-8 -*-

from __future__ import print_function

import hashlib
import os
import sys
from difflib import SequenceMatcher, unified_diff
from functools import wraps
from io import open
from itertools import groupby

from junit_xml import TestSuite, TestCase
from pony.orm import Database, Required, db_session, Set, Optional, select, \
    PrimaryKey, RowNotFound, ERDiagramError, OperationalError

from mutmut import BAD_TIMEOUT, OK_SUSPICIOUS, BAD_SURVIVED, UNTESTED, \
    OK_KILLED, MutationID, Context, mutate

try:
    from itertools import zip_longest
except ImportError:  # pragma: no cover (python2)
    from itertools import izip_longest as zip_longest


if sys.version_info >= (3, 5):   # pragma: no cover (python 2 specific)
    # add tying library for doc improvements
    from typing import Generator, Sequence

if sys.version_info < (3, 0):   # pragma: no cover (python 2 specific)
    # noinspection PyUnresolvedReferences
    text_type = unicode
    # This little hack is needed to get the click tester working on python 2.7
    orig_print = print

    def print(x='', **kwargs):
        x = x.decode("utf-8")
        orig_print(x.encode("utf-8"), **kwargs)

else:
    from itertools import zip_longest
    text_type = str


db = Database()

current_db_version = 2


class MiscData(db.Entity):
    key = PrimaryKey(text_type, auto=True)
    value = Optional(text_type, autostrip=False)


class SourceFile(db.Entity):
    filename = Required(text_type, autostrip=False)
    lines = Set('Line')


class Line(db.Entity):
    sourcefile = Required(SourceFile)
    line = Optional(text_type, autostrip=False)
    line_number = Required(int)
    mutants = Set('Mutant')


class Mutant(db.Entity):
    line = Required(Line)
    index = Required(int)
    tested_against_hash = Optional(text_type, autostrip=False)
    status = Required(text_type, autostrip=False)  # really an enum of mutant_statuses


def init_db(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if db.provider is None:
            cache_filename = os.path.join(os.getcwd(), '.mutmut-cache')
            db.bind(provider='sqlite', filename=cache_filename, create_db=True)

            try:
                db.generate_mapping(create_tables=True)
            except OperationalError:
                pass

            if os.path.exists(cache_filename):
                # If the existing cache file is out of data, delete it and start over
                with db_session:
                    try:
                        v = MiscData.get(key='version')
                        if v is None:
                            existing_db_version = 1
                        else:
                            existing_db_version = int(v.value)
                    except (RowNotFound, ERDiagramError, OperationalError):
                        existing_db_version = 1

                if existing_db_version != current_db_version:
                    print('mutmut cache is out of date, clearing it...')
                    db.drop_all_tables(with_all_data=True)
                    db.schema = None  # Pony otherwise thinks we've already created the tables
                    db.generate_mapping(create_tables=True)

            with db_session:
                v = get_or_create(MiscData, key='version')
                v.value = str(current_db_version)

        return f(*args, **kwargs)
    return wrapper


def hash_of_tests(tests_dirs):
    """Calculate a SHA256 hash from the contents of all testing files

    :param tests_dirs: list of paths of all testing directories
    :type tests_dirs: list[str]

    :return: a SHA256 hash string
    :rtype: str
    """
    m = hashlib.sha256()
    for tests_dir in tests_dirs:
        for root, dirs, files in os.walk(tests_dir):
            for filename in files:
                with open(os.path.join(root, filename), 'rb') as f:
                    m.update(f.read())
    return m.hexdigest()


@init_db
@db_session
def print_result_cache():
    """Print the mutation test results contained within the `.mutmut-cache`
    in a human readable format"""
    print('To apply a mutant on disk:')
    print('    mutmut apply <id>')
    print('')
    print('To show a mutant:')
    print('    mutmut show <id>')
    print('')

    def print_stuff(title, query):
        l = list(query)
        if l:
            print('')
            print("{} ({})".format(title, len(l)))
            for filename, mutants in groupby(l, key=lambda x: x.line.sourcefile.filename):
                mutants = list(mutants)
                print('')
                print("---- {} ({}) ----".format(filename, len(mutants)))
                print('')
                print(', '.join([str(x.id) for x in mutants]))

    print_stuff('Timed out ⏰', select(x for x in Mutant if x.status == BAD_TIMEOUT))
    print_stuff('Suspicious 🤔', select(x for x in Mutant if x.status == OK_SUSPICIOUS))
    print_stuff('Survived 🙁', select(x for x in Mutant if x.status == BAD_SURVIVED))
    print_stuff('Untested', select(x for x in Mutant if x.status == UNTESTED))


def get_unified_diff(pk, dict_synonyms):
    """

    :param pk: primary key of a :class:`MutationID` within the cache
    :type pk: int

    :param dict_synonyms: list of synonyms of python dictionary objects
    :type dict_synonyms: list[str]

    :return:
    :rtype: str
    """
    filename, mutation_id = filename_and_mutation_id_from_pk(pk)
    with open(filename) as f:
        source = f.read()
    context = Context(
        source=source,
        filename=filename,
        mutation_id=mutation_id,
        dict_synonyms=dict_synonyms,
    )
    mutated_source, number_of_mutations_performed = mutate(context)
    if not number_of_mutations_performed:
        return ""

    output = ""
    for line in unified_diff(source.split('\n'), mutated_source.split('\n'), fromfile=filename, tofile=filename, lineterm=''):
        output += line + "\n"
    return output


@init_db
@db_session
def print_result_cache_junitxml(dict_synonyms, suspicious_policy, untested_policy):
    """Print the mutation test results contained within the `.mutmut-cache`
    styled similar too junit xml

    :param dict_synonyms: list of synonyms of python dictionary objects
    :type dict_synonyms: list[str]

    :param suspicious_policy:
    :type suspicious_policy: str

    :param untested_policy:
    :type untested_policy: str
    """
    test_cases = []
    l = list(select(x for x in Mutant))
    for filename, mutants in groupby(l, key=lambda x: x.line.sourcefile.filename):
        for mutant in mutants:
            tc = TestCase("Mutant #{}".format(mutant.id), file=filename, line=mutant.line.line_number, stdout=mutant.line.line)
            if mutant.status == BAD_SURVIVED:
                tc.add_failure_info(message=mutant.status, output=get_unified_diff(mutant.id, dict_synonyms))
            if mutant.status == BAD_TIMEOUT:
                tc.add_error_info(message=mutant.status, error_type="timeout", output=get_unified_diff(mutant.id, dict_synonyms))
            if mutant.status == OK_SUSPICIOUS:
                if suspicious_policy != 'ignore':
                    func = getattr(tc, 'add_{}_info'.format(suspicious_policy))
                    func(message=mutant.status, output=get_unified_diff(mutant.id, dict_synonyms))
            if mutant.status == UNTESTED:
                if untested_policy != 'ignore':
                    func = getattr(tc, 'add_{}_info'.format(untested_policy))
                    func(message=mutant.status, output=get_unified_diff(mutant.id, dict_synonyms))

            test_cases.append(tc)

    ts = TestSuite("mutmut", test_cases)
    print(TestSuite.to_xml_string([ts]))


def get_or_create(model, defaults=None, **params):
    if defaults is None:
        defaults = {}
    obj = model.get(**params)
    if obj is None:
        params = params.copy()
        for k, v in defaults.items():
            if k not in params:
                params[k] = v
        return model(**params)
    else:
        return obj


def sequence_ops(a, b):
    """

    :param a:
    :type a: Sequence[Any]
    :param b:
    :type b: Sequence[Any]

    :return:
    :rtype: Generator[tuple[Any], None, None]
    """
    sequence_matcher = SequenceMatcher(a=a, b=b)

    for tag, i1, i2, j1, j2 in sequence_matcher.get_opcodes():
        a_sub_sequence = a[i1:i2]
        b_sub_sequence = b[j1:j2]
        for x in zip_longest(a_sub_sequence, range(i1, i2), b_sub_sequence, range(j1, j2)):
            yield (tag,) + x


@init_db
@db_session
def update_line_numbers(filename):
    """

    :param filename:
    :type filename: str
    """
    sourcefile = get_or_create(SourceFile, filename=filename)

    cached_line_objects = list(sourcefile.lines.order_by(Line.line_number))

    cached_lines = [x.line for x in cached_line_objects]

    with open(filename) as f:
        # :-1 to remove newline at the end
        existing_lines = [x[:-1] for x in f.readlines()]

    if not cached_lines:
        for i, line in enumerate(existing_lines):
            Line(sourcefile=sourcefile, line=line, line_number=i)
        return

    for command, a, a_index, b, b_index in sequence_ops(cached_lines, existing_lines):
        if command == 'equal':
            if a_index != b_index:
                cached_obj = cached_line_objects[a_index]
                assert cached_obj.line == existing_lines[b_index]
                cached_obj.line_number = b_index

        elif command == 'delete':
            cached_line_objects[a_index].delete()

        elif command == 'insert':
            Line(sourcefile=sourcefile, line=b, line_number=b_index)

        elif command == 'replace':
            cached_line_objects[a_index].delete()
            Line(sourcefile=sourcefile, line=b, line_number=b_index)

        else:
            assert False, 'unknown opcode from SequenceMatcher: %s' % command


@init_db
@db_session
def register_mutants(mutations_by_file):
    """

    :param mutations_by_file:
    :type mutations_by_file: dict[str, list[MutationID]]
    """
    for filename, mutation_ids in mutations_by_file.items():
        sourcefile = get_or_create(SourceFile, filename=filename)

        for mutation_id in mutation_ids:
            line = Line.get(sourcefile=sourcefile, line=mutation_id.line, line_number=mutation_id.line_number)
            assert line is not None
            get_or_create(Mutant, line=line, index=mutation_id.index, defaults=dict(status=UNTESTED))


@init_db
@db_session
def set_cached_mutant_status(file_to_mutate, mutation_id, status, tests_hash):
    """Set the status of a **existing** mutant in the cache

    :param file_to_mutate:
    :type file_to_mutate: str

    :param mutation_id:
    :type mutation_id: MutationID

    :param status:
    :type status: str

    :param tests_hash:
    :type tests_hash: str
    """
    sourcefile = SourceFile.get(filename=file_to_mutate)
    line = Line.get(sourcefile=sourcefile, line=mutation_id.line, line_number=mutation_id.line_number)
    mutant = Mutant.get(line=line, index=mutation_id.index)
    mutant.status = status
    mutant.tested_against_hash = tests_hash


@init_db
@db_session
def get_cached_mutation_status(filename, mutation_id, tests_hash):
    """Get the status of a **existing** mutant in the cache

    :param filename:
    :type filename: str

    :param mutation_id:
    :type mutation_id: MutationID

    :param tests_hash:
    :type tests_hash: str

    :return: the status of the specified mutant
    :rtype: str
    """
    sourcefile = SourceFile.get(filename=filename)
    line = Line.get(sourcefile=sourcefile, line=mutation_id.line, line_number=mutation_id.line_number)
    mutant = Mutant.get(line=line, index=mutation_id.index)

    if mutant.status == OK_KILLED:
        # We assume that if a mutant was killed, a change to the test
        # suite will mean it's still killed
        return OK_KILLED

    if mutant.tested_against_hash != tests_hash:
        return UNTESTED

    return mutant.status


@init_db
@db_session
def mutation_id_from_pk(pk):
    """

    :param pk:
    :type pk: int

    :return:
    :rtype: MutationID
    """
    mutant = Mutant.get(id=pk)
    return MutationID(line=mutant.line.line, index=mutant.index, line_number=mutant.line.line_number)


@init_db
@db_session
def filename_and_mutation_id_from_pk(pk):
    """

    :param pk: primary key of a :class:`MutationID` within the cache
    :type pk: int

    :return:
    :rtype: tuple[str, MutationID]
    """
    mutant = Mutant.get(id=pk)
    return mutant.line.sourcefile.filename, mutation_id_from_pk(pk)


@init_db
@db_session
def cached_test_time():
    """Get the baseline test execution time from the cache

    :rtype: float or None
    """
    d = MiscData.get(key='baseline_time_elapsed')
    return float(d.value) if d else None


@init_db
@db_session
def set_cached_test_time(baseline_time_elapsed):
    """Set the baseline test execution time in the cache

    :type baseline_time_elapsed: float
    """
    get_or_create(MiscData, key='baseline_time_elapsed').value = str(baseline_time_elapsed)
