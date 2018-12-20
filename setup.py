#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""setup.py for muckup"""

import os
import re
import sys

from setuptools import setup, find_packages
from setuptools.command.test import test

README = open('README.rst').read()
NAME = "muckup"


def read_version():
    with open(os.path.join(NAME, '__init__.py')) as f:
        m = re.search(r'''__version__\s*=\s*['"]([^'"]*)['"]''', f.read())
        if m:
            return m.group(1)
        raise ValueError("couldn't find version")


VERSION = read_version()


class Pylint(test):
    def run_tests(self):
        from pylint.lint import Run
        Run([NAME, "--persistent", "y", "--rcfile", ".pylintrc",
             "--output-format", "colorized"])


class PyTest(test):
    user_options = [('pytest-args=', 'a', "Arguments to pass to pytest")]

    def initialize_options(self):
        test.initialize_options(self)
        self.pytest_args = "-v --cov={}".format(NAME)

    def run_tests(self):
        import shlex
        # import here, cause outside the eggs aren't loaded
        import pytest
        errno = pytest.main(shlex.split(self.pytest_args))
        sys.exit(errno)


import inspect
running_inside_tests = any(['pytest' in x[1] for x in inspect.stack()])

# NB: _don't_ add namespace_packages to setup(), it'll break
#     everything using imp.find_module
setup(
    name=NAME,
    version=VERSION,
    description='Simple mutation testing for python.',
    long_description=README,
    author='Nathan Klapstien',
    author_email='nklapste@ualberta.ca',
    url='https://github.com/nklapste/muckup',
    packages=find_packages(),
    include_package_data=True,
    license="BSD",
    zip_safe=False,
    keywords='mutation testing test mutant',
    install_requires=[
        "glob2",
        "parso",
        "python-nonblock"
    ],
    tests_require=[
        "pytest>=2.8.7",
        "pytest-cov",
        "pylint>=1.9.1,<2.0.0",
        "pytest-testmon",
    ],
    classifiers=[
        'Development Status :: 4 - Beta',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: BSD License',
        'Natural Language :: English',
        "Programming Language :: Python :: 2",
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.4',
        'Programming Language :: Python :: 3.5',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3.7',
        "Framework :: Pytest",
    ],
    test_suite='tests',
    cmdclass={
        "test": PyTest,
        "lint": Pylint
    },
    # if I add entry_points while pytest runs,
    # it imports before the coverage collecting starts
    entry_points={
        'pytest11': [
            'muckup = muckup.pytestplugin',
        ]
    } if running_inside_tests else {},
    scripts=['bin/muckup'],
)
