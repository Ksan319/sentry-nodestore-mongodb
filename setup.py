#!/usr/bin/env python

from setuptools import setup

install_requires = [
    'boto3>=1.34.8',
    'botocore>=1.17.8',
    'pymongo>=3.6.1',
]

setup(
    name='sentry-nodestore-mongodb',
    version='1.0.0',
    description='A Sentry plugin to add MongoDb as a NodeStore backend.',
    packages=['sentry_nodestore_mongodb'],
    install_requires=install_requires,
)
