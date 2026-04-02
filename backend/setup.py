"""
Setup script for the KidsChat package.
"""

from setuptools import find_packages, setup

setup(
    name="jubu_chat",
    version="1.0.0",
    description="Child-friendly conversational AI system",
    author="KidsChat Team",
    author_email="team@kidschat.example",
    packages=find_packages(include=["jubu_chat", "jubu_chat.*"]),
    python_requires=">=3.8",
    install_requires=[
        "pydantic>=2.0.0",
        "pyyaml>=6.0",
        "pytest>=7.0.0",
        "pytest-mock>=3.10.0",
        "python-dotenv>=0.20.0",
    ],
    extras_require={
        "dev": [
            "black",
            "isort",
            "mypy",
            "pylint",
            "pytest-cov",
        ],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
    ],
)
