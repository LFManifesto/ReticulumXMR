#!/usr/bin/env python3
from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as f:
    long_description = f.read()

setup(
    name="lxmfmonero",
    version="0.1.0",
    author="Light Fighter Manifesto L.L.C.",
    author_email="contact@lightfightermanifesto.org",
    description="Monero transactions over LXMF/Reticulum mesh networks",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/LFManifesto/LXMFMonero",
    packages=find_packages(),
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Topic :: Communications",
        "Topic :: Security :: Cryptography",
    ],
    python_requires=">=3.9",
    install_requires=[
        "rns>=0.7.0",
        "lxmf>=0.4.0",
        "requests>=2.28.0",
    ],
    entry_points={
        "console_scripts": [
            "lxmfmonero-hub=lxmfmonero.hub:main",
            "lxmfmonero-client=lxmfmonero.client:main",
            "lxmfmonero-tui=lxmfmonero.tui:main",
        ],
    },
)
