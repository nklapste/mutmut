#!/usr/bin/python
# -*- coding: utf-8 -*-

"""Mutation testing definitions and helpers"""

import sys
from enum import Enum
from shutil import move

from parso import parse
from parso.python.tree import Name

if sys.version_info < (3, 0):  # pragma: no cover (python 2 specific)
    # noinspection PyUnresolvedReferences
    text_types = (str, unicode)  # pylint: disable=undefined-variable
else:
    text_types = (str,)

# We have a global whitelist for constants of the
# pattern __all__, __version__, etc
DUNDER_WHITELIST = [
    'all',
    'version',
    'title',
    'package_name',
    'author',
    'description',
    'email',
    'version',
    'license',
    'copyright',
]


class MutantTestStatus(Enum):
    """Test statues a :class:`.Mutant` can have"""
    UNTESTED = 'UNTESTED'
    OK_KILLED = 'OK_KILLED'
    OK_SUSPICIOUS = 'OK_SUSPICIOUS'
    BAD_TIMEOUT = 'BAD_TIMEOUT'
    BAD_SURVIVED = 'BAD_SURVIVED'


class Mutant:

    def __init__(self,
                 filename=None,
                 source=None,
                 mutated_source=None,
                 status=MutantTestStatus.UNTESTED):
        """Construct a Mutant

        :param filename:
        :type filename: str or None

        :param source:
        :type source; str or None

        :param mutated_source:
        :type mutated_source; str or None

        :param status:
        :type status: MutantTestStatus
        """
        self.filename = filename
        self.source = source

        # to be set by MutantGenerator
        self.mutated_source = mutated_source

        self.status = status

        self.applied = False

    def __eq__(self, other):
        return (self.filename, self.source, self.mutated_source, self.status) == \
               (other.filename, other.source, other.mutated_source, other.status)

    @property
    def mutation_original_pair(self):
        mutant = set(self.mutated_source.splitlines(keepends=True))
        normie = set(self.source.splitlines(keepends=True))
        mutation = list(mutant - normie)
        original = list(normie - mutant)
        return original[0].strip(), mutation[0].strip()

    def apply(self):
        """Apply the mutation to the existing source file also create
        a backup"""
        if self.applied:
            raise RuntimeError("Mutant is applied. Call `Mutant.revert` "
                               "before calling `Mutant.apply` again")

        open(self.filename + '.bak', 'w').write(self.source)
        with open(self.filename, 'w') as f:
            f.write(self.mutated_source)

        self.applied = True

    def revert(self):
        """Revert the application of the mutation to the existing
        source file"""
        if not self.applied:
            raise RuntimeError("Mutant is not applied. Call `Mutant.apply` "
                               "before calling `Mutant.revert` again")
        move(self.filename + '.bak', self.filename)

        self.applied = False


def number_mutation(value, **_):
    suffix = ''
    if value.upper().endswith('L'):  # pragma: no cover (python 2 specific)
        suffix = value[-1]
        value = value[:-1]

    if value.upper().endswith('J'):
        suffix = value[-1]
        value = value[:-1]

    if value.startswith('0o'):
        base = 8
        value = value[2:]
    elif value.startswith('0x'):
        base = 16
        value = value[2:]
    elif value.startswith('0b'):
        base = 2
        value = value[2:]
    elif value.startswith('0') and len(value) > 1 and value[1] != '.':  # pragma: no cover (python 2 specific)
        base = 8
        value = value[1:]
    else:
        base = 10

    try:
        parsed = int(value, base=base)
    except ValueError:
        # Since it wasn't an int, it must be a float
        parsed = float(value)

    result = repr(parsed + 1)
    if not result.endswith(suffix):
        result += suffix
    return result


def string_mutation(value, **_):
    prefix = value[
             :min([x for x in [value.find('"'), value.find("'")] if x != -1])]
    value = value[len(prefix):]

    if value.startswith('"""') or value.startswith("'''"):
        # We assume here that triple-quoted stuff are docs or other things
        # that mutation is meaningless for
        return value
    return prefix + value[0] + 'XX' + value[1:-1] + 'XX' + value[-1]


def lambda_mutation(children, **_):
    from parso.python.tree import Name
    if len(children) != 4 or getattr(children[-1], 'value', '---') != 'None':
        return children[:3] + \
               [Name(value=' None', start_pos=children[0].start_pos)]
    return children[:3] + [Name(value=' 0', start_pos=children[0].start_pos)]


def argument_mutation(children, context, **_):
    """
    :type context: Mutator
    """
    if len(context.stack) >= 3 and \
            context.stack[-3].type in ('power', 'atom_expr'):
        stack_pos_of_power_node = -3
    elif len(context.stack) >= 4 and \
            context.stack[-4].type in ('power', 'atom_expr'):
        stack_pos_of_power_node = -4
    else:
        return children

    power_node = context.stack[stack_pos_of_power_node]

    if power_node.children[0].type == 'name' and \
            power_node.children[0].value in ['dict']:
        children = children[:]
        child = children[0]
        if child.type == 'name':
            children[0] = Name(child.value + 'XX', start_pos=child.start_pos,
                               prefix=child.prefix)

    return children


def keyword_mutation(value, context, **_):
    if len(context.stack) > 2 and \
            context.stack[-2].type == 'comp_op' and \
            value in ('in', 'is'):
        return value

    if len(context.stack) > 1 and context.stack[-2].type == 'for_stmt':
        return value

    return {
        # 'not': 'not not',
        'not': '',
        # this will cause "is not not" sometimes,
        # so there's a hack to fix that later
        'is': 'is not',
        'in': 'not in',
        'break': 'continue',
        'continue': 'break',
        'True': 'False',
        'False': 'True',
    }.get(value, value)


def operator_mutation(value, context, **_):
    if context.stack[-2].type in ('import_from', 'param'):
        return value

    return {
        '+': '-',
        '-': '+',
        '*': '/',
        '/': '*',
        '//': '/',
        '%': '/',
        '<<': '>>',
        '>>': '<<',
        '&': '|',
        '|': '&',
        '^': '&',
        '**': '*',
        '~': '',

        '+=': '-=',
        '-=': '+=',
        '*=': '/=',
        '/=': '*=',
        '//=': '/=',
        '%=': '/=',
        '<<=': '>>=',
        '>>=': '<<=',
        '&=': '|=',
        '|=': '&=',
        '^=': '&=',
        '**=': '*=',
        '~=': '=',

        '<': '<=',
        '<=': '<',
        '>': '>=',
        '>=': '>',
        '==': '!=',
        '!=': '==',
        '<>': '==',
    }.get(value, value)


def and_or_test_mutation(children, node, **_):
    children = children[:]
    from parso.python.tree import Keyword
    children[1] = Keyword(
        value={'and': ' or', 'or': ' and'}[children[1].value],
        start_pos=node.start_pos,
    )
    return children


def expression_mutation(children, **_):
    def handle_assignment(children):
        if getattr(children[2], 'value', '---') != 'None':
            x = ' None'
        else:
            x = ' 7'
        children = children[:]
        children[2] = Name(value=x, start_pos=children[2].start_pos)

        return children

    if children[0].type == 'operator' and children[0].value == ':':
        if len(children) > 2 and children[2].value == '=':
            children[1:] = handle_assignment(children[1:])
    elif children[1].type == 'operator' and children[1].value == '=':
        children = handle_assignment(children)

    return children


def decorator_mutation(children, **_):
    assert children[-1].type == 'newline'
    return children[-1:]


def trailer_mutation(children, **_):
    if len(children) == 3 and \
            children[0].type == 'operator' and \
            children[0].value == '[' and \
            children[-1].type == 'operator' and \
            children[-1].value == ']' and \
            children[0].parent.type == 'trailer' and \
            children[1].type == 'name' and \
            children[1].value != 'None':
        # Something that looks like "foo[bar]"
        return [children[0], Name(value='None', start_pos=children[0].start_pos), children[-1]]
    return children


def arglist_mutation(children, **_):
    if len(children) > 3 and \
            children[0].type == 'name' and \
            children[0].value != 'None':
        return [Name(value='None',
                     start_pos=children[0].start_pos)] + children[1:]
    return children


mutations_by_type = {
    'operator': dict(value=operator_mutation),
    'keyword': dict(value=keyword_mutation),
    'number': dict(value=number_mutation),
    'name': dict(
        value=lambda value, **_: {
            'True': 'False',
            'False': 'True',
            'deepcopy': 'copy',
            # TODO: This breaks some tests, so should figure out why first: 'None': '0',
            # TODO: probably need to add a lot of things here... some builtins maybe, what more?
        }.get(value, value)),
    'string': dict(value=string_mutation),
    'argument': dict(children=argument_mutation),
    'or_test': dict(children=and_or_test_mutation),
    'and_test': dict(children=and_or_test_mutation),
    'lambdef': dict(children=lambda_mutation),
    'expr_stmt': dict(children=expression_mutation),
    'decorator': dict(children=decorator_mutation),
    'annassign': dict(children=expression_mutation),
    'trailer': dict(children=trailer_mutation),
    'arglist': dict(children=arglist_mutation),
}


class Mutator:
    def __init__(self, source=None, filename=None,
                 exclude=lambda context: False):
        self.source = source
        self.filename = filename
        self.exclude = exclude

        self.stack = []
        self.index = 0
        self.current_line_index = 0
        self._source_by_line_number = None
        self._pragma_no_mutate_lines = None

    def exclude_line(self):
        current_line = self.source_by_line_number[self.current_line_index]
        if current_line.startswith('__'):
            word, _, rest = current_line[2:].partition('__')
            if word in DUNDER_WHITELIST and rest.strip()[0] == '=':
                return True

        if current_line.strip() == \
                "__import__('pkg_resources').declare_namespace(__name__)":
            return True

        return self.current_line_index in self.pragma_no_mutate_lines or \
            self.exclude(context=self)

    @property
    def source_by_line_number(self):
        if self._source_by_line_number is None:
            self._source_by_line_number = self.source.split('\n')
        return self._source_by_line_number

    @property
    def current_source_line(self):
        return self.source_by_line_number[self.current_line_index]

    @property
    def pragma_no_mutate_lines(self):
        if self._pragma_no_mutate_lines is None:
            self._pragma_no_mutate_lines = {
                line_number
                for line_number, line in enumerate(self.source_by_line_number)
                if '# pragma:' in line and
                   'no mutate' in line.partition('# pragma:')[-1]
            }
        return self._pragma_no_mutate_lines

    def yield_mutants(self):
        yield from self.mutate_list_of_nodes(
            parse(self.source, error_recovery=False)
        )

    def mutate_list_of_nodes(self, node):
        for child in node.children:
            if child.type == 'operator' and child.value == '->':
                return
            yield from self.mutate_node(child)

    def mutate_node(self, node):
        if node.type == 'tfpdef':
            return

        self.stack.append(node)
        try:
            if node.start_pos[0] - 1 != self.current_line_index:
                self.current_line_index = node.start_pos[0] - 1
                # indexes are unique per line, so start over here!
                self.index = 0

            if hasattr(node, 'children'):
                yield from self.mutate_list_of_nodes(node)

            mutations = mutations_by_type.get(node.type)

            if mutations is None:
                return

            for node_key, mutation_operation in sorted(mutations.items()):
                if self.exclude_line():
                    continue
                old = getattr(node, node_key)
                new = mutation_operation(
                    context=self,
                    node=node,
                    value=getattr(node, 'value', None),
                    children=getattr(node, 'children', None),
                )
                if new != old:
                    setattr(node, node_key, new)
                    yield Mutant(
                        filename=self.filename,
                        source=self.source,
                        mutated_source=node.get_root_node().get_code().replace(' not not ', ' ')
                    )
                    setattr(node, node_key, old)
                    self.index += 1
        finally:
            self.stack.pop()
