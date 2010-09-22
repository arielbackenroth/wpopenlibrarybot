from setuptools import setup, find_packages
import glob, os
from stat import *

def executable(path):
    st = os.stat(path)[ST_MODE]
    return (st & S_IEXEC) and not S_ISDIR(st)

setup(name='wpopenlibarywp',
      version='0.1',
      description='OpenlibraryBot',
      packages=find_packages(exclude=["ez_setup"]),
      scripts=filter(executable, glob.glob('scripts/*')),
      install_requires=('simplejson', 'termcolor', 'wikitools'))
