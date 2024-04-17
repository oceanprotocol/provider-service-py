#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright 2023 Ocean Protocol Foundation
# SPDX-License-Identifier: Apache-2.0
#

"""The setup script."""

#  Copyright 2018 Ocean Protocol Foundation
#  SPDX-License-Identifier: Apache-2.0

from setuptools import find_packages, setup

with open("README.md") as readme_file:
    readme = readme_file.read()

# Installed by pip install ocean-provider
# or pip install -e .
install_requirements = [
    "ocean-contracts==2.0.2",
    "web3==5.25.0",
    "Flask==2.1.2",
    "Flask-Cors==3.0.9",
    "flask_caching==1.10.1",
    "Flask-RESTful==0.3.8",
    "flask-swagger==0.2.14",
    "flask-swagger-ui==3.25.0",
    "Jinja2>=2.10.1,<3.1",
    "gunicorn==22.0.0",
    "coloredlogs==15.0.1",
    "Werkzeug==2.0.3",
    "eciespy==0.3.11",
    "coincurve>=13,<15",
    "ipaddress==1.0.23",
    "dnspython==2.2.1",
    "flask-sieve==1.3.1",
    "SQLAlchemy==1.3.23",
    "redis==4.5.4",
    "enforce-typing==1.0.0.post1",
    "pyjwt==2.4.0",
    "pysha3==1.0.2",
]

# Required to run setup.py:
setup_requirements = ["pytest-runner"]

test_requirements = [
    "codacy-coverage==1.3.11",
    "coverage==6.4.4",
    "docker==6.0.0",
    "freezegun==1.1.0",
    "mccabe==0.7.0",
    "pytest==7.1.2",
    "pytest-env==0.6.2",
    "requests_testadapter==0.3.0",
]

# Possibly required by developers of ocean-provider:
dev_requirements = [
    "bumpversion==0.6.0",
    "pkginfo",
    "twine",
    "python-dotenv==0.15.0",
    "flake8==5.0.4",
    "isort==5.10.1",
    "black==22.6.0",
    "pre-commit==2.20.0",
    "licenseheaders==0.8.8",
]

setup(
    author="leucothia",
    author_email="devops@oceanprotocol.com",
    classifiers=[
        "Development Status :: 2 - Pre-Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: Apache Software License",
        "Natural Language :: English",
        "Programming Language :: Python :: 3.8",
    ],
    description="🐳 Ocean Provider.",
    extras_require={
        "test": test_requirements,
        "dev": dev_requirements + test_requirements,
    },
    install_requires=install_requirements,
    license="Apache Software License 2.0",
    long_description=readme,
    long_description_content_type="text/markdown",
    include_package_data=True,
    keywords="ocean-provider",
    name="ocean-provider",
    packages=find_packages(
        include=["ocean_provider", "ocean_provider.utils", "ocean_provider.app"]
    ),
    setup_requires=setup_requirements,
    test_suite="tests",
    tests_require=test_requirements,
    url="https://github.com/oceanprotocol/provider-py",
    # fmt: off
    # bumpversion needs single quotes
    version='2.1.6',
    # fmt: on
    zip_safe=False,
)
