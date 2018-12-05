#!/usr/bin/python
# -*- coding: utf-8 -*-

import hashlib
import os
from functools import wraps
from io import open
from itertools import groupby
from logging import getLogger

from pony.orm import Database, Required, db_session, Set, Optional, select, \
    PrimaryKey

from mutmut.mutators import BAD_TIMEOUT, OK_SUSPICIOUS, BAD_SURVIVED, UNTESTED, \
    OK_KILLED

db = Database()

__log__ = getLogger(__name__)


class MiscData(db.Entity):
    key = PrimaryKey(str, auto=True)
    value = Optional(str, autostrip=False)


class SourceFile(db.Entity):
    filename = Required(str, autostrip=False)
    lines = Set('Line')


class Line(db.Entity):
    sourcefile = Required(SourceFile)
    line = Required(str, autostrip=False)
    mutants = Set('Mutant')


class Mutant(db.Entity):
    line = Required(Line)
    index = Required(int)
    tested_against_hash = Optional(str, autostrip=False)
    status = Required(str,
                      autostrip=False)  # really an enum of mutant_statuses


def init_db(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if db.provider is None:
            db.bind(provider='sqlite', filename=os.path.join(os.getcwd(), '.mutmut-cache'), create_db=True)
            db.generate_mapping(create_tables=True)

        return f(*args, **kwargs)
    return wrapper


def hash_of(filename):
    with open(filename, 'rb') as f:
        m = hashlib.sha256()
        m.update(f.read())
        return m.hexdigest()


def hash_of_tests(tests_dirs):
    m = hashlib.sha256()
    for tests_dir in tests_dirs:
        for root, dirs, files in os.walk(tests_dir):
            for filename in files:
                with open(os.path.join(root, filename), 'rb') as f:
                    m.update(f.read())
    return m.hexdigest()


def get_apply_line(mutant):
    apply_line = 'mutmut apply %s' % mutant.id
    return apply_line


@init_db
@db_session
def print_result_cache():
    print('To apply a mutant on disk:')
    print('    mutmut apply <id>')
    print()
    print('To show a mutant:')
    print('    mutmut show <id>')
    print()

    def print_stuff(title, query):
        l = list(query)
        if l:
            print()
            print(title, '(%s)' % len(l))
            for filename, mutants in groupby(l, key=lambda x: x.line.sourcefile.filename):
                mutants = list(mutants)
                print()
                print('-' * 4, '%s' % filename, '(%s)' % len(mutants), '-' * 4)
                print()
                print(', '.join([str(x.id) for x in mutants]))

    print_stuff('Timed out ⏰', select(x for x in Mutant if x.status == BAD_TIMEOUT))
    print_stuff('Suspicious 🤔', select(x for x in Mutant if x.status == OK_SUSPICIOUS))
    print_stuff('Survived 🙁', select(x for x in Mutant if x.status == BAD_SURVIVED))
    print_stuff('Untested', select(x for x in Mutant if x.status == UNTESTED))


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


@init_db
@db_session
def register_mutants(mutations_by_file):
    for filename, mutation_ids in mutations_by_file.items():
        sourcefile = get_or_create(SourceFile, filename=filename)
        lines_to_be_removed = {x.id: x for x in sourcefile.lines}
        for mutation_id in mutation_ids:
            line = get_or_create(Line, sourcefile=sourcefile, line=mutation_id[0])
            get_or_create(Mutant, line=line, index=mutation_id[1], defaults=dict(status=UNTESTED))
            if line.id in lines_to_be_removed:
                del lines_to_be_removed[line.id]

        # These lines no longer exists in the code, clean them out
        for line in lines_to_be_removed.values():
            line.delete()


@init_db
@db_session
def update_mutant_status(file_to_mutate, mutation_id, status, tests_hash):
    sourcefile = SourceFile.get(filename=file_to_mutate)
    line = Line.get(sourcefile=sourcefile, line=mutation_id[0])
    mutant = Mutant.get(line=line, index=mutation_id[1])
    mutant.status = status
    mutant.tested_against_hash = tests_hash


@init_db
@db_session
def cached_mutation_status(filename, mutation_id, hash_of_tests):
    sourcefile = SourceFile.get(filename=filename)
    line = Line.get(sourcefile=sourcefile, line=mutation_id[0])
    mutant = Mutant.get(line=line, index=mutation_id[1])

    if mutant.status == OK_KILLED:
        # We assume that if a mutant was killed, a change to the test suite will mean it's still killed
        return OK_KILLED

    if mutant.tested_against_hash != hash_of_tests:
        return UNTESTED

    return mutant.status


@init_db
@db_session
def mutation_id_from_pk(pk):
    mutant = Mutant.get(id=pk)
    return mutant.line.line, mutant.index


@init_db
@db_session
def filename_and_mutation_id_from_pk(pk):
    mutant = Mutant.get(id=pk)
    return mutant.line.sourcefile.filename, mutation_id_from_pk(pk)


@init_db
@db_session
def cached_test_time():
    d = MiscData.get(key='baseline_time_elapsed')
    return float(d.value) if d else None


@init_db
@db_session
def set_cached_test_time(baseline_time_elapsed):
    get_or_create(MiscData, key='baseline_time_elapsed').value = str(baseline_time_elapsed)
