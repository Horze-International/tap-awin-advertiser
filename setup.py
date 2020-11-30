#!/usr/bin/env python

from setuptools import setup, find_packages

setup(name='tap-awin-advertiser',
      version="0.2.1",
      description='Singer.io tap for extracting data from the AWIN Advertiser API',
      author='Horze',
      url='http://horze.de',
      classifiers=['Programming Language :: Python :: 3 :: Only'],
      py_modules=['tap_awin_advertiser'],
      install_requires=[
          'singer-python==5.9.0',
          'backoff==1.8.0',
          'requests==2.24.0',
          'pyhumps==1.6.1'
      ],
      entry_points='''
          [console_scripts]
          tap-awin-advertiser=tap_awin_advertiser:main
      ''',
      packages=find_packages(),
      package_data = {
          'tap_awin_advertiser': [
              'schemas/*.json',
          ],
      },
      extras_require={
          'dev': [
              'pylint',
              'ipdb',
          ]
      },
)