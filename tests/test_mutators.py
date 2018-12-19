#!/usr/bin/python
# -*- coding: utf-8 -*-

"""pytests for :mod:`muckup.mutators`"""

import sys

import pytest

from muckup.mutators import Mutator

from parso.parser import ParserSyntaxError


@pytest.mark.parametrize(
    'original, expected', [
        ('a(b, c, d, e, f)', 'a(None, c, d, e, f)'),
        ('a[b]', 'a[None]'),
        # ("1 in (1, 2)", "2 not in (2, 3)"),
        ("1 in (1, 2)", "1 not in (1, 2)"),
        # ('1+1', '2-2'),
        ('1+1', '1-1'),
        ('1', '2'),
        ('1-1', '1+1'),
        ('1*1', '1/1'),
        # ('1/1', '2*2'),
        # ('1/1', '1*2'),
        ('1/1', '1/2'),
        # ('1.0', '1.0000000000000002'),  # using numpy features
        ('1.0', '2.0'),
        ('0.1', '1.1'),
        ('1e-3', '1.001'),
        ('True', 'False'),
        ('False', 'True'),
        ('"foo"', '"XXfooXX"'),
        ("'foo'", "'XXfooXX'"),
        ("u'foo'", "u'XXfooXX'"),
        ("0", "1"),
        ("0o0", "1"),
        ("0.", "1.0"),
        ("0x0", "1"),
        ("0b0", "1"),
        # ("1<2", "2<=3"),
        ("1<2", "1<=2"),
        # ('(1, 2)', '(2, 3)'),
        ('(1, 2)', '(1, 3)'),
        # ("1 not in (1, 2)", "2  in (2, 3)"),  # two spaces here because "not in" is two words
        ("1 not in (1, 2)", "1  in (1, 2)"),  # two spaces here because "not in" is two words
        ("foo is foo", "foo is not foo"),
        ("foo is not foo", "foo is  foo"),
        # ("x if a else b", "x if a else b"),  # gen no mutant
        ('a or b', 'a and b'),
        ('a and b', 'a or b'),
        ('a = b', 'a = None'),
        ('s[0]', 's[1]'),
        # ('s[0] = a', 's[1] = None'),
        ('s[0] = a', 's[0] = None'),
        ('s[1:]', 's[2:]'),
        ('1j', '2j'),
        ('1.0j', '2.0j'),
        ('0o1', '2'),
        ('1.0e10', '10000000001.0'),
        ("dict(a=b)", "dict(aXX=b)"),
        ('lambda **kwargs: Variable.integer(**setdefaults(kwargs, dict(show=False)))', 'lambda **kwargs: None'),
        ('lambda **kwargs: None', 'lambda **kwargs: 0'),
        ('a = {x for x in y}', 'a = None'),
        ('a = None', 'a = 7'),
        ('break', 'continue'),
    ]
)
def test_basic_mutations(original, expected):
    mutants = list(Mutator(source=original).yield_mutants())
    assert any(mutant.mutated_source == expected for mutant in mutants)
    assert any(mutant.mutated_source != original for mutant in mutants)


@pytest.mark.skipif(sys.version_info < (3, 0),
                    reason="Don't check Python 3 syntax in Python 2")
@pytest.mark.parametrize(
    'original, expected', [
        ('def foo(s: Int = 1): pass', 'def foo(s: Int = 2): pass')
    ]
)
def test_basic_mutations_python3(original, expected):
    mutants = list(Mutator(source=original).yield_mutants())
    assert len(mutants) == 1
    assert mutants[0].mutated_source == expected


@pytest.mark.skipif(sys.version_info < (3, 6),
                    reason="Don't check Python 3.6+ syntax in Python < 3.6")
@pytest.mark.parametrize(
    'original, expected', [
        ('a: int = 1', 'a: int = 2'),
        ('a: Optional[int] = None', 'a: Optional[None] = None'),
    ]
)
def test_basic_mutations_python36(original, expected):
    mutants = list(Mutator(source=original).yield_mutants())
    assert len(mutants) == 1
    assert any(mutant.mutated_source == expected for mutant in mutants)


@pytest.mark.parametrize(
    'source', [
        "'''foo'''",  # don't mutate things we assume to be docstrings
        "NotADictSynonym(a=b)",
        'from foo import *',
        'import foo',
        'import foo as bar',
        'foo.bar',
        'for x in y: pass',
        'a[None]',
        'a(None)',
    ]
)
def test_do_not_mutate(source):
    assert len(list(Mutator(source=source).yield_mutants())) == 0


@pytest.mark.skipif(sys.version_info < (3, 0), reason="Don't check Python 3 syntax in Python 2")
@pytest.mark.parametrize(
    'source', [
        'def foo(s: str): pass'
    ]
)
def test_do_not_mutate_python3(source):
    assert len(list(Mutator(source=source).yield_mutants())) == 0


def test_function():
    source = \
        "def capitalize(s):\n    return s[0].upper() + s[1:] if s else s\n"
    mutants = list(Mutator(source=source).yield_mutants())
    assert len(mutants) == 3
    assert mutants[0].mutated_source == \
           "def capitalize(s):\n    return s[1].upper() + s[1:] if s else s\n"
    assert mutants[1].mutated_source == \
           "def capitalize(s):\n    return s[0].upper() - s[1:] if s else s\n"
    assert mutants[2].mutated_source == \
           "def capitalize(s):\n    return s[0].upper() + s[2:] if s else s\n"


@pytest.mark.skipif(sys.version_info < (3, 0),
                    reason="Don't check Python 3 syntax in Python 2")
def test_function_with_annotation():
    source = \
        "def capitalize(s : str):\n    return s[0].upper() + s[1:] if s else s\n"

    mutants = list(Mutator(source=source).yield_mutants())
    assert len(mutants) == 3
    assert mutants[0].mutated_source == \
           "def capitalize(s : str):\n    return s[1].upper() + s[1:] if s else s\n"
    assert mutants[1].mutated_source == \
           "def capitalize(s : str):\n    return s[0].upper() - s[1:] if s else s\n"
    assert mutants[2].mutated_source == \
           "def capitalize(s : str):\n    return s[0].upper() + s[2:] if s else s\n"


def test_pragma_no_mutate():
    source = """def foo():\n    return 1+1  # pragma: no mutate\n"""
    mutants = list(Mutator(source=source).yield_mutants())
    assert len(mutants) == 0


def test_pragma_no_mutate_and_no_cover():
    source = """def foo():\n    return 1+1  # pragma: no cover, no mutate\n"""
    mutants = list(Mutator(source=source).yield_mutants())
    assert len(mutants) == 0


def test_mutate_decorator():
    source = """@foo\ndef foo():\n    pass\n"""
    mutants = list(Mutator(source=source).yield_mutants())
    assert len(mutants) == 1
    assert mutants[0].mutated_source == source.replace('@foo', '')


def test_mutate_decorator2():
    source = """\"""foo\"""\n@foo\ndef foo():\n    pass\n"""
    mutants = list(Mutator(source=source).yield_mutants())
    assert len(mutants) == 1
    assert mutants[0].mutated_source == source.replace('@foo', '')


def test_mutate_dict():
    source = "dict(a=b, c=d)"
    mutants = list(Mutator(source=source).yield_mutants())
    assert len(mutants) == 2
    assert mutants[0].mutated_source == "dict(aXX=b, c=d)"
    assert mutants[1].mutated_source == "dict(a=b, cXX=d)"


def test_syntax_error():
    with pytest.raises(ParserSyntaxError):
        list(Mutator(source=':!').yield_mutants())


def test_bug_github_issue_18():
    source = """@register.simple_tag(name='icon')
def icon(name):
    if name is None:
        return ''
    tpl = '<span class="glyphicon glyphicon-{}"></span>'
    return format_html(tpl, name)"""
    # TODO: inspect test
    assert len(list(Mutator(source=source).yield_mutants())) == 6


def test_bug_github_issue_19():
    source = """key = lambda a: "foo"  
filters = dict((key(field), False) for field in fields)"""
    mutants = list(Mutator(source=source).yield_mutants())

    assert len(mutants) == 6
    assert mutants[0].mutated_source == """key = lambda a: "XXfooXX"  
filters = dict((key(field), False) for field in fields)"""
    assert mutants[1].mutated_source == """key = lambda a: None  
filters = dict((key(field), False) for field in fields)"""
    assert mutants[2].mutated_source == """key = None  
filters = dict((key(field), False) for field in fields)"""
    assert mutants[3].mutated_source == """key = lambda a: "foo"  
filters = dict((key(field), True) for field in fields)"""
    assert mutants[4].mutated_source == """key = lambda a: "foo"  
filters = dict((key(field), False) for field not in fields)"""
    assert mutants[5].mutated_source == """key = lambda a: "foo"  
filters = None"""



@pytest.mark.skipif(sys.version_info < (3, 6),
                    reason="Don't check Python 3.6+ syntax in Python < 3.6")
def test_bug_github_issue_26():
    source = """
class ConfigurationOptions(Protocol):
    min_name_length: int
    """
    Mutator(source=source).yield_mutants()


@pytest.mark.skipif(sys.version_info < (3, 0),
                    reason="Don't check Python 3 syntax in Python 2")
def test_bug_github_issue_30():
    source = """
def from_checker(cls: Type['BaseVisitor'], checker) -> 'BaseVisitor':
    pass
"""
    mutants = list(Mutator(source=source).yield_mutants())
    assert len(mutants) == 0
