from setuptools import setup, find_packages

with open("README.md", "r") as fh:
    long_description = fh.read()

setup(
    name="netx_hboot_image_compiler",
    version = "3.0.19",
    author="Paul Fox",
    author_email="paul.fox@temposonics.com",
    description="Image compiler for Hilscher netX90 Second-Stage Bootloader",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/pfox89/netx_hboot_image_compiler.git",
    packages=find_packages(),
    classifiers=[
        "Programming Language :: Python :: 3.7",
        "Operating System :: OS Independent",
        "Topic :: Software Development :: Embedded Systems",
        "License :: OSI Approved :: GNU General Public License v2 (GPLv2)"
    ],
    package_data={
        "":["*.xml"],
    },
    include_package_data=True,
    python_requires='>=3.7',
)