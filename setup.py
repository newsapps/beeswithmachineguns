#!/usr/bin/env python

from distutils.core import setup

setup(name='beeswithmachineguns',
      version='0.1.0',
      description='A utility for arming (creating) many bees (micro EC2 instances) to attack (load test) targets (web applications).',
      author='Christopher Groskopf',
      author_email='cgroskopf@tribune.com',
      url='http://github.com/newsapps/beeswithmachineguns',
      license='MIT',
      packages=['beeswithmachineguns'],
      scripts = ['bwmg'],
     )
