#!/usr/bin/env python

try:
    from setuptools import setup
except ImportError:
    from distutils.core import setup

with open('requirements.txt') as f:
    required_packages = f.readlines()

setup(name='beeswithmachineguns',
      version='0.1.4',
      description='A utility for arming (creating) many bees (micro EC2 instances) to attack (load test) targets (web applications).',
      author='Christopher Groskopf',
      author_email='cgroskopf@tribune.com',
      url='http://github.com/newsapps/beeswithmachineguns',
      license='MIT',
      packages=['beeswithmachineguns'],
      scripts=['bees'],
      install_requires=required_packages,
      classifiers=[
          'Development Status :: 4 - Beta',
          'Environment :: Console',
          'Intended Audience :: Developers',
          'License :: OSI Approved :: MIT License',
          'Natural Language :: English',
          'Operating System :: OS Independent',
          'Programming Language :: Python',
          'Topic :: Software Development :: Testing :: Traffic Generation',
          'Topic :: Utilities',
          ],
     )
