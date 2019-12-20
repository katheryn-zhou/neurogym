import re
from setuptools import setup, find_packages
import sys

if sys.version_info.major != 3:
    print('This Python is only compatible with Python 3, but you are running '
          'Python {}. The installation will likely fail.'.format(sys.version_info.major))


extras = {}

all_deps = []
for group_name in extras:
    all_deps += extras[group_name]

extras['all'] = all_deps

setup(name='neurogym',
      packages=[package for package in find_packages()
                if package.startswith('neurogym')],
      install_requires=[
          'gym',
      ],
      extras_require=extras,
      description='NeuroGym: Gym-style cognitive neuroscience tasks',
      author='Manuel Molano and Guangyu Robert Yang',
      url='https://github.com/gyyang/neurogym',
      version='0.0.1')