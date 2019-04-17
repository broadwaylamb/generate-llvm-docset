# generate-llvm-docset

A Python 3 script for generating [Dash](https://kapeli.com/dash) docset for LLVM API.

### Usage

TL;DR:
```
$ git clone https://github.com/broadwaylamb/generate-llvm-docset.git
$ cd generate-llvm-docset
$ ./generate-llvm-docset --help

usage: generate-docset.py [-h] [--clean] [--doxygen-path DOXYGEN_PATH]
                          [--dot-path DOT_PATH] [--skip-docset-generation]
                          [-q] [-v]
                          llvm_version

positional arguments:
  llvm_version          LLVM version string (e. g. 8.0.0)

optional arguments:
  -h, --help            show this help message and exit
  --clean               Download and regenerate everything from scratch
  --doxygen-path DOXYGEN_PATH
                        The path to doxygen executable
  --dot-path DOT_PATH   The path to dot (from Graphviz) executable
  --skip-docset-generation
                        Only generate HTML documentation, without Dash .docset
                        file
  -q, --quiet           Suppress the output
  -v, --verbose         Shot output of doxygen and other tools

```

Create a directory where the generated files will be located, and run the script from there:

```
$ mkdir build
$ ../generate-llvm-docset 8.0.0
```

You can specify any LLVM version you want.

### Prerequisites

- `doxygen` — can be installed via [Homebrew](http://brew.sh/): `brew install doxygen`
- `dot` — a part of Graphviz, can also be installed via Homebrew: `brew install graphviz`
